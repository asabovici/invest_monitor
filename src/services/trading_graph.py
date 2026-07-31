"""Trading-graph service: run / get-state / resume for the LangGraph pipeline.

Slice 8 of the API refactor — see API_REFACTOR_PLAN.md §5. Wraps
``src.trading_graph.build_graph`` behind a UUID-keyed run cache so HTTP
clients can start a run, inspect its state at a HITL pause, and resume
once a human has reviewed.

Two layers of caching:

1. **Compiled-graph cache** (``_get_compiled_graph``) — keyed on the
   frozen ``Settings`` instance. Each compiled graph has its own
   ``MemorySaver`` checkpointer that tracks all runs sharing that
   settings hash.
2. **Run record cache** (``_runs``) — UUID-keyed dict storing
   ``(thread_id, settings)`` so we can look up the right compiled graph
   on resume / get-state.

Process-local; runs are lost across uvicorn restarts.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from langchain_core.messages import BaseMessage

from src.services.schemas.trading_graph import (
    MessageTurn,
    RunState,
    TradingGraphSettings,
)
from src.trading_graph import Settings, build_graph, initial_state


# ── Compiled-graph cache ─────────────────────────────────────────────────────


@lru_cache(maxsize=16)
def _get_compiled_graph(settings: Settings):
    """One compiled graph per ``Settings`` value. The MemorySaver inside is
    shared across every run that uses the same settings."""
    return build_graph(settings)


def _settings_from_schema(schema: TradingGraphSettings | None) -> Settings:
    if schema is None:
        return Settings()
    return Settings(
        model_name=schema.model_name,
        human_in_the_loop=schema.human_in_the_loop,
        max_revisions=schema.max_revisions,
        var_limit=schema.var_limit,
        max_sector_concentration=schema.max_sector_concentration,
    )


def _settings_to_schema(settings: Settings) -> TradingGraphSettings:
    return TradingGraphSettings(
        model_name=settings.model_name,
        human_in_the_loop=settings.human_in_the_loop,
        max_revisions=settings.max_revisions,
        var_limit=settings.var_limit,
        max_sector_concentration=settings.max_sector_concentration,
    )


# ── Run records ──────────────────────────────────────────────────────────────


@dataclass
class _RunRecord:
    run_id: str
    thread_id: str
    settings: Settings
    created_at: datetime


_runs: dict[str, _RunRecord] = {}
_runs_lock = threading.Lock()


def reset_runs() -> None:
    """Drop the run cache. Tests call this between cases."""
    with _runs_lock:
        _runs.clear()
    _get_compiled_graph.cache_clear()


def _get_run(run_id: str) -> _RunRecord:
    with _runs_lock:
        record = _runs.get(run_id)
    if record is None:
        raise ValueError(f"Run {run_id!r} not found.")
    return record


# ── State conversion ─────────────────────────────────────────────────────────


def _message_to_turn(m: Any) -> MessageTurn:
    """``BaseMessage`` from langchain has ``.content`` and ``.type``; dict
    fallback for raw dicts."""
    if isinstance(m, BaseMessage):
        content = m.content if isinstance(m.content, str) else str(m.content)
        return MessageTurn(role=m.type or "assistant", content=content)
    if isinstance(m, dict):
        return MessageTurn(role=str(m.get("role", "assistant")), content=str(m.get("content", "")))
    return MessageTurn(role="assistant", content=str(m))


def _snapshot_to_run_state(record: _RunRecord, snapshot: Any) -> RunState:
    """Translate a LangGraph ``StateSnapshot`` into the wire schema."""
    values = snapshot.values if snapshot is not None else {}
    next_nodes = list(snapshot.next) if snapshot is not None and snapshot.next else []
    is_complete = not next_nodes
    is_paused_for_hitl = (
        record.settings.human_in_the_loop and "cio" in next_nodes
    )

    messages = [_message_to_turn(m) for m in values.get("messages", [])]
    return RunState(
        run_id=record.run_id,
        settings=_settings_to_schema(record.settings),
        created_at=record.created_at,
        is_complete=is_complete,
        is_paused_for_hitl=is_paused_for_hitl,
        next_nodes=next_nodes,
        market_signal=values.get("market_signal"),
        whitelist=list(values.get("whitelist") or []),
        proposed_trades=values.get("proposed_trades"),
        risk_approved=bool(values.get("risk_approved", False)),
        risk_critique=list(values.get("risk_critique") or []),
        final_execution_ready=bool(values.get("final_execution_ready", False)),
        revision_count=int(values.get("revision_count", 0)),
        messages=messages,
    )


# ── Public service surface ───────────────────────────────────────────────────


def start_run(settings_schema: TradingGraphSettings | None = None) -> RunState:
    """Open a new run and execute up to the first interrupt (or completion).

    Returns the snapshot after the first ``invoke``. With HITL on, the
    return reflects the state at the pause before the CIO; with HITL
    off, the run runs to completion in this call.
    """
    settings = _settings_from_schema(settings_schema)
    graph = _get_compiled_graph(settings)
    run_id = uuid.uuid4().hex
    thread_id = uuid.uuid4().hex
    record = _RunRecord(
        run_id=run_id,
        thread_id=thread_id,
        settings=settings,
        created_at=datetime.now(timezone.utc),
    )
    with _runs_lock:
        _runs[run_id] = record

    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(initial_state(), config=config)
    snapshot = graph.get_state(config)
    return _snapshot_to_run_state(record, snapshot)


def get_run_state(run_id: str) -> RunState:
    """Current snapshot for a run. Raises ``ValueError`` if unknown."""
    record = _get_run(run_id)
    graph = _get_compiled_graph(record.settings)
    config = {"configurable": {"thread_id": record.thread_id}}
    snapshot = graph.get_state(config)
    return _snapshot_to_run_state(record, snapshot)


def resume_run(run_id: str, state_patch: dict | None = None) -> RunState:
    """Resume from the current interrupt, optionally patching state first.

    A ``state_patch`` like ``{"proposed_trades": {...}}`` is applied via
    ``graph.update_state`` (reducers still apply), then the graph
    continues. Raises ``ValueError`` if the run is unknown.
    """
    record = _get_run(run_id)
    graph = _get_compiled_graph(record.settings)
    config = {"configurable": {"thread_id": record.thread_id}}
    if state_patch:
        graph.update_state(config, state_patch)
    graph.invoke(None, config=config)
    snapshot = graph.get_state(config)
    return _snapshot_to_run_state(record, snapshot)


def end_run(run_id: str) -> None:
    """Drop a run record. Idempotent: missing IDs raise 404.

    The underlying checkpointer entry is left in place — the
    ``MemorySaver`` doesn't expose a deletion API, but it's bounded by
    process lifetime anyway.
    """
    with _runs_lock:
        if run_id not in _runs:
            raise ValueError(f"Run {run_id!r} not found.")
        del _runs[run_id]


__all__ = [
    "start_run",
    "get_run_state",
    "resume_run",
    "end_run",
    "reset_runs",
]

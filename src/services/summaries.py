"""Conversation-summaries service.

Thin wrapper around ``src.agent_summaries`` that surfaces pydantic
models, normalises ValueErrors, and adds the "save the active session"
flow (``save_summary_from_session``).

Slice 7 of the API refactor — see API_REFACTOR_PLAN.md §5.
"""

from __future__ import annotations

from src import agent_summaries
from src.services.agents import _session_client, _session_messages
from src.services.schemas.summary import (
    SummaryDetail,
    SummaryInfo,
    SummaryTurn,
)


# ── Reads ────────────────────────────────────────────────────────────────────


def list_summaries(data_dir: str, agent: str | None = None) -> list[SummaryInfo]:
    """Return all summaries (optionally filtered by agent kind), newest first."""
    return [_to_info(s) for s in agent_summaries.list_summaries(data_dir=data_dir, agent=agent)]


def get_summary(data_dir: str, key: str) -> SummaryDetail:
    """Return one summary with transcript. Raises ``ValueError`` if missing."""
    entry = agent_summaries.get_summary(key, data_dir=data_dir)
    if entry is None:
        raise ValueError(f"Summary {key!r} not found.")
    return _to_detail({"key": key, **entry})


# ── Writes ───────────────────────────────────────────────────────────────────


def save_summary_from_session(data_dir: str, session_id: str) -> SummaryDetail:
    """Compress the live session's transcript via Haiku and persist it.

    Re-uses the session's own ``anthropic.Anthropic`` client so we don't
    spin up a second one just to summarise.

    Raises:
        ValueError: session unknown or the conversation is empty.
    """
    kind, session_data_dir, messages = _session_messages(session_id)
    # Persist in the session's own data dir if the caller didn't override.
    target_dir = data_dir or session_data_dir
    if not messages:
        raise ValueError("Cannot summarise an empty conversation.")
    client = _session_client(session_id)
    key, entry = agent_summaries.save_summary(
        agent=kind,
        messages=messages,
        client=client,
        data_dir=target_dir,
    )
    return _to_detail({"key": key, **entry})


def delete_summary(data_dir: str, key: str) -> None:
    """Drop one summary. Raises ``ValueError`` if missing."""
    if not agent_summaries.delete_summary(key, data_dir=data_dir):
        raise ValueError(f"Summary {key!r} not found.")


# ── Mapping helpers ──────────────────────────────────────────────────────────


def _to_info(d: dict) -> SummaryInfo:
    return SummaryInfo(
        key=d.get("key", ""),
        agent=d.get("agent", ""),
        started_at=d.get("started_at", ""),
        summary=d.get("summary", ""),
        message_count=int(d.get("message_count", 0)),
    )


def _to_detail(d: dict) -> SummaryDetail:
    transcript_raw = d.get("transcript") or []
    transcript: list[SummaryTurn] = []
    for t in transcript_raw:
        role = t.get("role", "assistant") if isinstance(t, dict) else "assistant"
        content = t.get("content", "") if isinstance(t, dict) else str(t)
        if isinstance(content, list):
            content = "".join(
                str(getattr(b, "text", b.get("text", "") if isinstance(b, dict) else ""))
                for b in content
            )
        transcript.append(SummaryTurn(role=role, content=str(content)))
    return SummaryDetail(
        key=d.get("key", ""),
        agent=d.get("agent", ""),
        started_at=d.get("started_at", ""),
        summary=d.get("summary", ""),
        message_count=int(d.get("message_count", 0)),
        transcript=transcript,
    )


__all__ = [
    "list_summaries",
    "get_summary",
    "save_summary_from_session",
    "delete_summary",
]

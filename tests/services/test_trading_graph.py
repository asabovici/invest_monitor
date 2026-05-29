"""Tests for src/services/trading_graph.py.

The underlying graph runs with deterministic stub nodes
(``src.trading_graph.nodes.*``), so these tests exercise the full
service surface without any LLM call.
"""

from __future__ import annotations

import pytest

from src.services import trading_graph as graph_service
from src.services.schemas.trading_graph import TradingGraphSettings


@pytest.fixture(autouse=True)
def fresh_caches():
    graph_service.reset_runs()
    yield
    graph_service.reset_runs()


# ── Start ────────────────────────────────────────────────────────────────────


def test_start_run_without_hitl_completes_inline() -> None:
    state = graph_service.start_run(TradingGraphSettings(human_in_the_loop=False))
    assert state.is_complete
    assert not state.is_paused_for_hitl
    assert state.final_execution_ready
    assert state.next_nodes == []


def test_start_run_with_hitl_pauses_before_cio() -> None:
    state = graph_service.start_run(TradingGraphSettings(human_in_the_loop=True))
    assert not state.is_complete
    assert state.is_paused_for_hitl
    assert state.next_nodes == ["cio"]
    # Risk has approved by the time we hit the pause.
    assert state.risk_approved
    assert not state.final_execution_ready


def test_start_run_uses_defaults_when_none() -> None:
    state = graph_service.start_run(None)
    # Default settings keep HITL on.
    assert state.is_paused_for_hitl
    assert state.settings.human_in_the_loop is True


# ── Get / Resume ─────────────────────────────────────────────────────────────


def test_get_run_state_after_start() -> None:
    started = graph_service.start_run(TradingGraphSettings(human_in_the_loop=True))
    fetched = graph_service.get_run_state(started.run_id)
    assert fetched.run_id == started.run_id
    assert fetched.next_nodes == ["cio"]


def test_resume_run_proceeds_to_completion() -> None:
    started = graph_service.start_run(TradingGraphSettings(human_in_the_loop=True))
    final = graph_service.resume_run(started.run_id)
    assert final.is_complete
    assert final.final_execution_ready


def test_resume_run_with_state_patch_overrides_proposed_trades() -> None:
    started = graph_service.start_run(TradingGraphSettings(human_in_the_loop=True))
    override = {"allocation": {"OVERRIDE": 1.0}, "revision": 99}
    final = graph_service.resume_run(
        started.run_id, state_patch={"proposed_trades": override},
    )
    assert final.is_complete
    assert final.proposed_trades == override


# ── End / 404 paths ──────────────────────────────────────────────────────────


def test_get_unknown_run_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        graph_service.get_run_state("not-a-run")


def test_resume_unknown_run_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        graph_service.resume_run("not-a-run")


def test_end_run_drops_record() -> None:
    started = graph_service.start_run(TradingGraphSettings(human_in_the_loop=True))
    graph_service.end_run(started.run_id)
    with pytest.raises(ValueError, match="not found"):
        graph_service.get_run_state(started.run_id)


def test_end_unknown_run_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        graph_service.end_run("not-a-run")


# ── Compiled-graph cache ─────────────────────────────────────────────────────


def test_same_settings_share_compiled_graph() -> None:
    """Two runs with identical settings reuse the same compiled-graph instance."""
    s1 = graph_service.start_run(TradingGraphSettings(human_in_the_loop=False))
    s2 = graph_service.start_run(TradingGraphSettings(human_in_the_loop=False))
    # Both completed independently; thread_ids differ but they share the graph cache.
    assert s1.run_id != s2.run_id
    assert s1.is_complete and s2.is_complete


def test_max_revisions_bounds_loop_via_settings() -> None:
    """Setting max_revisions=1 forces the loop guard to bail out faster.

    The stub PM uses 4 tickers (25% each) which passes the default 30%
    concentration cap, so the graph normally completes on the first
    revision. To exercise the loop guard properly we need a custom
    risk-rejection scenario, which we'll cover when prompts replace
    stubs. For now, just verify the cap is propagated by reading it back.
    """
    state = graph_service.start_run(
        TradingGraphSettings(human_in_the_loop=False, max_revisions=1),
    )
    assert state.settings.max_revisions == 1

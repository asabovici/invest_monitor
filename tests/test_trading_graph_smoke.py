"""End-to-end smoke + HITL tests for the trading graph."""

import pytest

from src.trading_graph.config import Settings
from src.trading_graph.graph import build_graph
from src.trading_graph.state import initial_state


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def test_graph_runs_end_to_end_without_hitl() -> None:
    app = build_graph(Settings(human_in_the_loop=False))
    final = app.invoke(initial_state(), config=_config("no-hitl"))

    assert final["final_execution_ready"] is True
    assert final["risk_approved"] is True
    assert final["proposed_trades"] is not None
    assert final["market_signal"] is not None
    # Loop guard: revision_count should be bounded by max_revisions (3 default).
    assert final["revision_count"] <= Settings().max_revisions


def test_hitl_pauses_before_cio_then_resumes() -> None:
    app = build_graph(Settings(human_in_the_loop=True))
    cfg = _config("with-hitl")

    paused = app.invoke(initial_state(), config=cfg)
    # Before resume: risk approved, but CIO has not yet acted.
    assert paused["risk_approved"] is True
    assert paused["final_execution_ready"] is False

    # Resume by invoking with None — checkpointer continues from the interrupt.
    resumed = app.invoke(None, config=cfg)
    assert resumed["final_execution_ready"] is True


def test_max_revisions_bounds_the_loop(monkeypatch) -> None:
    """If risk never approves, the graph still terminates via the loop guard."""
    from src.trading_graph.nodes import risk_manager as rm_module

    def always_reject(state, settings=None):
        return {
            "risk_approved": False,
            "risk_critique": ["stub forced rejection"],
            "messages": [],
        }

    monkeypatch.setattr(rm_module, "risk_manager_node", always_reject)

    # Rebuild graph after patching the node import target.
    from src.trading_graph import graph as graph_module

    monkeypatch.setattr(graph_module, "risk_manager_node", always_reject)

    app = graph_module.build_graph(Settings(human_in_the_loop=False, max_revisions=2))
    final = app.invoke(initial_state(), config=_config("forced-loop"))

    assert final["final_execution_ready"] is False
    assert final["revision_count"] >= 2
    # risk_critique accumulates across rejections — never overwritten.
    assert len(final["risk_critique"]) >= 2

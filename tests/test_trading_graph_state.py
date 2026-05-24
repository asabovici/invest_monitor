"""Verify TradingState reducer semantics: append vs last-write-wins."""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from src.trading_graph.state import TradingState, initial_state


def _apply_updates(updates: list[dict]) -> TradingState:
    """Drive the reducers by running a tiny graph that yields each update in turn."""
    g: StateGraph = StateGraph(TradingState)

    nodes: list[str] = []
    for i, upd in enumerate(updates):
        name = f"n{i}"
        nodes.append(name)
        g.add_node(name, (lambda u: lambda _state: u)(upd))

    g.add_edge(START, nodes[0])
    for a, b in zip(nodes, nodes[1:]):
        g.add_edge(a, b)
    g.add_edge(nodes[-1], END)

    compiled = g.compile()
    return compiled.invoke(initial_state())


def test_initial_state_defaults() -> None:
    s = initial_state()
    assert s["market_signal"] is None
    assert s["whitelist"] == []
    assert s["proposed_trades"] is None
    assert s["risk_approved"] is False
    assert s["risk_critique"] == []
    assert s["final_execution_ready"] is False
    assert s["revision_count"] == 0
    assert s["messages"] == []


def test_risk_critique_appends() -> None:
    state = _apply_updates(
        [
            {"risk_critique": ["concentration too high"]},
            {"risk_critique": ["VaR exceeds limit"]},
        ]
    )
    assert state["risk_critique"] == ["concentration too high", "VaR exceeds limit"]


def test_messages_append() -> None:
    state = _apply_updates(
        [
            {"messages": [HumanMessage(content="hello")]},
            {"messages": [AIMessage(content="hi back")]},
        ]
    )
    assert [m.content for m in state["messages"]] == ["hello", "hi back"]


def test_scalar_fields_overwrite() -> None:
    state = _apply_updates(
        [
            {"revision_count": 1, "risk_approved": False},
            {"revision_count": 2, "risk_approved": True},
        ]
    )
    assert state["revision_count"] == 2
    assert state["risk_approved"] is True


def test_dict_field_overwrites() -> None:
    state = _apply_updates(
        [
            {"proposed_trades": {"AAPL": 10}},
            {"proposed_trades": {"MSFT": 5}},
        ]
    )
    assert state["proposed_trades"] == {"MSFT": 5}

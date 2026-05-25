"""Assemble and compile the trading StateGraph.

No business logic lives here — only nodes, edges, the checkpointer, and the
HITL interrupt list, per Section 5 of the spec.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .config import Settings
from .nodes import (
    cio_node,
    portfolio_manager_node,
    researcher_node,
    risk_manager_node,
)
from .routing import route_after_cio, route_after_risk
from .state import TradingState


def build_graph(settings: Settings | None = None):
    """Compile the trading graph. Returns a runnable LangGraph app.

    Invocations must pass ``config={"configurable": {"thread_id": ...}}`` so
    the ``MemorySaver`` checkpointer can track a run.
    """
    settings = settings or Settings()

    g: StateGraph = StateGraph(TradingState)
    g.add_node("researcher", researcher_node)
    g.add_node("portfolio_manager", portfolio_manager_node)
    g.add_node("risk_manager", lambda s: risk_manager_node(s, settings=settings))
    g.add_node("cio", cio_node)

    g.add_edge(START, "researcher")
    g.add_edge("researcher", "portfolio_manager")
    g.add_edge("portfolio_manager", "risk_manager")
    g.add_conditional_edges(
        "risk_manager",
        lambda s: route_after_risk(s, settings=settings),
        {
            "portfolio_manager": "portfolio_manager",
            "cio": "cio",
            "__end__": END,
        },
    )
    g.add_conditional_edges(
        "cio",
        route_after_cio,
        {
            "researcher": "researcher",
            "__end__": END,
        },
    )

    checkpointer = MemorySaver()
    interrupt_before = ["cio"] if settings.human_in_the_loop else []
    return g.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)

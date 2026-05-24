"""Shared state schema for the multi-agent trading graph.

Reducers:
- ``messages`` appends via ``add_messages``.
- ``risk_critique`` appends via ``operator.add``.
- All other keys are last-write-wins (default TypedDict behaviour in LangGraph).
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class TradingState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    market_signal: dict | None
    whitelist: list[str]
    proposed_trades: dict | None
    risk_approved: bool
    risk_critique: Annotated[list[str], operator.add]
    final_execution_ready: bool
    revision_count: int


def initial_state() -> TradingState:
    """Return a valid empty ``TradingState`` for a fresh run."""
    return TradingState(
        messages=[],
        market_signal=None,
        whitelist=[],
        proposed_trades=None,
        risk_approved=False,
        risk_critique=[],
        final_execution_ready=False,
        revision_count=0,
    )

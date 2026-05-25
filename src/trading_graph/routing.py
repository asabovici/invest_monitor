"""Conditional-edge functions for the trading graph.

Each returns the name of the next node as a string literal. ``max_revisions``
comes from ``Settings`` — never hardcode.
"""

from __future__ import annotations

from typing import Literal

from .config import Settings
from .state import TradingState


def route_after_risk(
    state: TradingState,
    settings: Settings | None = None,
) -> Literal["portfolio_manager", "cio", "__end__"]:
    """Route after the Risk Manager: approve → CIO, reject → PM (loop-bounded)."""
    settings = settings or Settings()
    if not state["risk_approved"]:
        if state["revision_count"] >= settings.max_revisions:
            return "__end__"
        return "portfolio_manager"
    return "cio"


def route_after_cio(state: TradingState) -> Literal["researcher", "__end__"]:
    """Route after the CIO: sign-off ends the run, otherwise loop to Researcher."""
    if state["final_execution_ready"]:
        return "__end__"
    return "researcher"

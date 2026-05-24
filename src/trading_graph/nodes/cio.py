"""CIO node — stub implementation.

Three terminal behaviours in the contract: sign off, request more research,
or override the proposed trades. Stub signs off whenever the risk manager has
approved.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from ..state import TradingState


def cio_node(state: TradingState) -> dict:
    """Sign off on the approved allocation."""
    if state.get("risk_approved"):
        return {
            "final_execution_ready": True,
            "messages": [AIMessage(content="cio: signed off, execution ready")],
        }

    # Defensive: if reached without approval, request more research.
    return {
        "final_execution_ready": False,
        "messages": [AIMessage(content="cio: requesting follow-up research")],
    }

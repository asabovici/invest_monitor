"""Risk Manager node — stub implementation.

Runs compliance checks on ``proposed_trades`` using thresholds from
``config.Settings``. The stub approves any well-formed proposal; tests cover
rejection paths by constructing state directly. Wiring real checks happens in
Section 9 step 8 of the spec.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from ..config import Settings
from ..state import TradingState


def risk_manager_node(state: TradingState, settings: Settings | None = None) -> dict:
    """Approve or reject ``state['proposed_trades']``.

    Returns ``{'risk_approved': bool, 'messages': [...]}``; on failure also
    appends one string to ``risk_critique``.
    """
    settings = settings or Settings()
    proposed = state.get("proposed_trades")

    if not proposed or not proposed.get("allocation"):
        critique = "risk: no allocation present in proposed_trades"
        return {
            "risk_approved": False,
            "risk_critique": [critique],
            "messages": [AIMessage(content=critique)],
        }

    # Stub concentration check using config.max_sector_concentration as a
    # per-ticker cap so the threshold actually flows from Settings.
    over_cap = [
        t for t, w in proposed["allocation"].items()
        if w > settings.max_sector_concentration
    ]
    if over_cap:
        critique = (
            f"risk: positions {over_cap} exceed max weight "
            f"{settings.max_sector_concentration:.0%}"
        )
        return {
            "risk_approved": False,
            "risk_critique": [critique],
            "messages": [AIMessage(content=critique)],
        }

    return {
        "risk_approved": True,
        "messages": [AIMessage(content="risk: approved")],
    }

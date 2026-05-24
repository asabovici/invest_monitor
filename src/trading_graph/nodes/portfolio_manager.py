"""Portfolio Manager node — stub implementation.

Reads the market signal and (if present) the latest risk critique to adjust
trades. Always increments ``revision_count`` so the loop guard can fire.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from ..state import TradingState


def portfolio_manager_node(state: TradingState) -> dict:
    """Emit a proposed-trades dict, optionally responding to a prior critique."""
    revision = state.get("revision_count", 0) + 1
    critiques = state.get("risk_critique") or []
    whitelist = state.get("whitelist") or ["AAPL", "MSFT", "JNJ", "BND"]

    # Stub allocation: even split across every whitelist ticker so per-position
    # weight stays under default concentration limits.
    weight = round(1.0 / len(whitelist), 4)
    proposed = {ticker: weight for ticker in whitelist}
    note = (
        f"portfolio_manager: revision {revision} responding to critique "
        f"'{critiques[-1]}'"
        if critiques
        else f"portfolio_manager: revision {revision} initial proposal"
    )
    return {
        "proposed_trades": {"allocation": proposed, "revision": revision},
        "revision_count": revision,
        "messages": [AIMessage(content=note)],
    }

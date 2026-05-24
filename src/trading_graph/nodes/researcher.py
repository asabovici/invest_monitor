"""Researcher node — stub implementation.

Reads optional CIO follow-up from messages/state and emits a market signal +
candidate whitelist. The deterministic stub lets the graph be exercised end to
end before real LLM prompts are wired in (Section 9 step 8 of the spec).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from ..state import TradingState


def researcher_node(state: TradingState) -> dict:
    """Produce a deterministic market signal and whitelist."""
    signal = {
        "regime": "neutral",
        "sectors_in_favor": ["Technology", "Healthcare"],
        "sectors_out": ["Energy"],
    }
    whitelist = ["AAPL", "MSFT", "JNJ", "BND"]
    return {
        "market_signal": signal,
        "whitelist": whitelist,
        "messages": [AIMessage(content="researcher: produced market signal stub")],
    }

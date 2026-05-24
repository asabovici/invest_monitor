"""Multi-agent investment coordination graph (LangGraph).

See SPEC_multi_agent_trading_system.md for the contract. Public surface:
``TradingState``, ``initial_state``, ``Settings``, ``build_graph``.
"""

from .config import Settings
from .graph import build_graph
from .state import TradingState, initial_state

__all__ = ["TradingState", "initial_state", "Settings", "build_graph"]

"""Settings for the multi-agent trading graph.

Risk thresholds and model names live here, never in node modules — see Section 6
of SPEC_multi_agent_trading_system.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    model_name: str = "claude-sonnet-4-20250514"
    human_in_the_loop: bool = True
    max_revisions: int = 3
    # VaR threshold (95% historical, fraction of portfolio value).
    # 5% chosen as a reasonable default for a moderately-aggressive portfolio.
    var_limit: float = 0.05
    max_sector_concentration: float = 0.30

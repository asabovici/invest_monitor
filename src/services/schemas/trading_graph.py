"""Pydantic schemas for the trading-graph endpoints (slice 8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TradingGraphSettings(BaseModel):
    """Wire shape for ``src.trading_graph.config.Settings``.

    Defaults mirror the dataclass — the service builds (or reuses a
    cached) ``Settings`` instance from this when starting a run.
    """

    model_name: str = "claude-sonnet-4-20250514"
    human_in_the_loop: bool = True
    max_revisions: int = Field(3, ge=1, le=20)
    var_limit: float = Field(0.05, ge=0.0, le=1.0)
    max_sector_concentration: float = Field(0.30, ge=0.0, le=1.0)


class StartRunRequest(BaseModel):
    """Body for ``POST /trading-graph/runs``.

    ``settings`` is optional; when omitted, the service uses the
    defaults baked into ``Settings``.
    """

    settings: TradingGraphSettings | None = None


class ResumeRunRequest(BaseModel):
    """Body for ``POST /trading-graph/runs/{id}/resume``.

    Two flavours of resume:
    - Plain (empty body): resume from the HITL interrupt as-is — the CIO
      will run with whatever ``risk_approved`` state already exists.
    - With ``state_patch``: apply arbitrary state overrides before
      resuming. Useful for forcing an override (e.g. CIO replaces
      ``proposed_trades``) or recording a sign-off note.

    The patch is applied via ``graph.update_state`` which honours the
    reducers — appending to ``risk_critique`` or ``messages`` works as
    expected.
    """

    state_patch: dict | None = None


class MessageTurn(BaseModel):
    """One turn of the persisted message list."""

    role: str
    content: str


class RunState(BaseModel):
    """Snapshot of a run as exposed to clients."""

    run_id: str
    settings: TradingGraphSettings
    created_at: datetime
    is_complete: bool = Field(
        ..., description="True when no next nodes are pending and the graph has terminated.",
    )
    is_paused_for_hitl: bool = Field(
        ..., description="True if execution is interrupted before the CIO awaiting sign-off.",
    )
    next_nodes: list[str] = Field(
        ..., description="Nodes that would run on the next invoke. Empty when complete.",
    )
    # Mirrors TradingState — see src/trading_graph/state.py.
    market_signal: dict | None = None
    whitelist: list[str] = Field(default_factory=list)
    proposed_trades: dict | None = None
    risk_approved: bool = False
    risk_critique: list[str] = Field(default_factory=list)
    final_execution_ready: bool = False
    revision_count: int = 0
    messages: list[MessageTurn] = Field(default_factory=list)

"""Pydantic schemas for scenario endpoints (slice 5).

Currently covers deterministic sector stress + the metadata catalogues
(stress, MC, regime). Monte Carlo + wealth projection schemas are
deferred (live in the agent skills today).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Catalogue rows ───────────────────────────────────────────────────────────


class StressScenarioInfo(BaseModel):
    """One entry in the sector-stress catalogue."""

    scenario_id: str
    sector_shocks: dict[str, float] = Field(
        ..., description="sector_key → shock as a fraction (e.g. -0.30 = -30%)."
    )
    non_equity_shocks: dict[str, float] = Field(
        ..., description="asset_type → shock fraction for Bond/Cash/CD/Crypto.",
    )


class MCScenarioPhaseInfo(BaseModel):
    """One phase of a multi-phase MC scenario."""

    name: str
    duration_days: int
    return_multiplier: float
    vol_multiplier: float
    one_time_shock: float


class MCScenarioInfo(BaseModel):
    scenario_id: str
    description: str
    phases: list[MCScenarioPhaseInfo]


class RegimePresetInfo(BaseModel):
    regime_id: str
    description: str
    returns_by_type: dict[str, float] = Field(
        ..., description="Annualised return per AssetType, percent (e.g. 5.9)."
    )
    vols_by_type: dict[str, float] = Field(
        ..., description="Annualised vol per AssetType, percent.",
    )


# ── Stress request + result ──────────────────────────────────────────────────


class StressTestRequest(BaseModel):
    """Body for ``POST /scenarios/stress/{portfolio_name}``.

    Either pick a named ``scenario_id`` or supply custom dicts. Custom
    values override anything pulled from the catalogue, so you can use
    e.g. ``"2008 Financial Crisis"`` as a base and bump a single sector.
    """

    scenario_id: str | None = None
    custom_sector_shocks: dict[str, float] | None = None
    custom_non_equity_shocks: dict[str, float] | None = None


class StressShockRow(BaseModel):
    ticker: str
    asset_type: str
    base_value: float
    shock_pct: float = Field(..., description="Per-position shock applied, percent.")
    new_value: float
    change_usd: float
    source: str = Field(
        ..., description="How the shock was derived (sector hit, avg fallback, fund profile, …).",
    )


class StressTestResult(BaseModel):
    portfolio_name: str
    scenario_id: str | None
    base_value: float
    new_value: float
    total_change_usd: float
    total_change_pct: float
    rows: list[StressShockRow]

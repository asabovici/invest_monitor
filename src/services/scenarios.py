"""Scenarios service: catalogues + deterministic sector stress.

Slice 5 of the API refactor — see API_REFACTOR_PLAN.md §5. Monte Carlo
and wealth projection live in the agent skills for now and migrate in
a later slice (likely with agents, slice 7).
"""

from __future__ import annotations

import pandas as pd

from src.services.schemas.scenario import (
    MCScenarioInfo,
    MCScenarioPhaseInfo,
    RegimePresetInfo,
    StressScenarioInfo,
    StressShockRow,
    StressTestResult,
)
from src.services._db import _get_db
from src.reporting import ReportingEngine
from src.scenarios import (
    NON_EQUITY_SHOCKS,
    SCENARIOS,
    SECTOR_STRESS_SCENARIOS,
    WEALTH_MC_PRESETS,
)


# ── Catalogue listings ───────────────────────────────────────────────────────


def list_stress_scenarios() -> list[StressScenarioInfo]:
    """Return all named one-shot sector stress scenarios with their shocks."""
    return [
        StressScenarioInfo(
            scenario_id=name,
            sector_shocks=dict(shocks),
            non_equity_shocks=dict(NON_EQUITY_SHOCKS.get(name, {})),
        )
        for name, shocks in SECTOR_STRESS_SCENARIOS.items()
    ]


def list_mc_scenarios() -> list[MCScenarioInfo]:
    """Return the catalogued multi-phase Monte Carlo scenarios."""
    return [
        MCScenarioInfo(
            scenario_id=name,
            description=s.description,
            phases=[
                MCScenarioPhaseInfo(
                    name=p.name,
                    duration_days=p.duration_days,
                    return_multiplier=p.return_multiplier,
                    vol_multiplier=p.vol_multiplier,
                    one_time_shock=p.one_time_shock,
                )
                for p in s.phases
            ],
        )
        for name, s in SCENARIOS.items()
    ]


def list_wealth_regimes() -> list[RegimePresetInfo]:
    """Historical regime presets used by the wealth MC projection."""
    return [
        RegimePresetInfo(
            regime_id=name,
            description=str(preset.get("description", "")),
            returns_by_type=dict(preset.get("returns", {})),
            vols_by_type=dict(preset.get("vols", {})),
        )
        for name, preset in WEALTH_MC_PRESETS.items()
    ]


# ── Sector stress ────────────────────────────────────────────────────────────


def run_sector_stress(
    data_dir: str,
    portfolio_name: str,
    *,
    scenario_id: str | None = None,
    custom_sector_shocks: dict[str, float] | None = None,
    custom_non_equity_shocks: dict[str, float] | None = None,
    latest_prices: dict[str, float] | None = None,
) -> StressTestResult:
    """Apply sector + non-equity shocks to a portfolio and report P/L per position.

    Resolution order for the two shock dicts:
      1. Start from ``SECTOR_STRESS_SCENARIOS[scenario_id]`` /
         ``NON_EQUITY_SHOCKS[scenario_id]`` if ``scenario_id`` is given.
      2. Merge in any ``custom_*`` overrides (per-key).

    Raises:
        ValueError: portfolio not found, or ``scenario_id`` unknown.
    """
    db = _get_db(data_dir)
    portfolio = db.get_portfolio(portfolio_name)  # raises if missing

    sector_shocks: dict[str, float] = {}
    non_equity: dict[str, float] = {}
    if scenario_id is not None:
        if scenario_id not in SECTOR_STRESS_SCENARIOS:
            raise ValueError(f"Unknown stress scenario_id: {scenario_id!r}")
        sector_shocks.update(SECTOR_STRESS_SCENARIOS[scenario_id])
        non_equity.update(NON_EQUITY_SHOCKS.get(scenario_id, {}))
    if custom_sector_shocks:
        sector_shocks.update(custom_sector_shocks)
    if custom_non_equity_shocks:
        non_equity.update(custom_non_equity_shocks)

    if not sector_shocks and not non_equity:
        raise ValueError(
            "No shocks specified — pass scenario_id or at least one custom_* dict.",
        )

    df = ReportingEngine(db).compute_sector_stress(
        portfolio,
        sector_shocks=sector_shocks,
        non_equity_shocks=non_equity,
        latest_prices=latest_prices,
    )

    if df.empty:
        return StressTestResult(
            portfolio_name=portfolio.name,
            scenario_id=scenario_id,
            base_value=0.0,
            new_value=0.0,
            total_change_usd=0.0,
            total_change_pct=0.0,
            rows=[],
        )

    rows = [
        StressShockRow(
            ticker=r["Ticker"],
            asset_type=r["Type"],
            base_value=float(r["Base Value"]),
            shock_pct=float(r["Shock %"]),
            new_value=float(r["New Value"]),
            change_usd=float(r["Change $"]),
            source=str(r["Source"]),
        )
        for _, r in df.iterrows()
    ]
    base_total = sum(r.base_value for r in rows)
    new_total = sum(r.new_value for r in rows)
    return StressTestResult(
        portfolio_name=portfolio.name,
        scenario_id=scenario_id,
        base_value=base_total,
        new_value=new_total,
        total_change_usd=new_total - base_total,
        total_change_pct=((new_total - base_total) / base_total * 100.0) if base_total else 0.0,
        rows=rows,
    )


# ── DataFrame helper for in-process callers (Streamlit) ──────────────────────


def stress_result_to_dataframe(result: StressTestResult) -> pd.DataFrame:
    """Convert a ``StressTestResult`` back to the legacy column shape."""
    if not result.rows:
        return pd.DataFrame(
            columns=["Ticker", "Type", "Base Value", "Shock %", "New Value", "Change $", "Source"]
        )
    return pd.DataFrame([{
        "Ticker": r.ticker,
        "Type": r.asset_type,
        "Base Value": r.base_value,
        "Shock %": r.shock_pct,
        "New Value": r.new_value,
        "Change $": r.change_usd,
        "Source": r.source,
    } for r in result.rows])


__all__ = [
    "list_stress_scenarios",
    "list_mc_scenarios",
    "list_wealth_regimes",
    "run_sector_stress",
    "stress_result_to_dataframe",
]

"""Tests for src/services/scenarios.py against the demo dataset."""

import pytest

from src.services.scenarios import (
    list_mc_scenarios,
    list_stress_scenarios,
    list_wealth_regimes,
    run_sector_stress,
    stress_result_to_dataframe,
)

DEMO = "data_demo"
PORTFOLIO = "Demo Brokerage"


# ── Catalogue listings ───────────────────────────────────────────────────────


def test_list_stress_scenarios_includes_known_presets() -> None:
    items = list_stress_scenarios()
    ids = {s.scenario_id for s in items}
    assert "2008 Financial Crisis" in ids
    assert "Rate Hike (2022-style)" in ids
    # Each entry should have at least one sector shock.
    for s in items:
        assert s.sector_shocks


def test_list_mc_scenarios_has_phases() -> None:
    items = list_mc_scenarios()
    assert items
    # The "base" scenario should be present and have at least one phase.
    base = next(s for s in items if s.scenario_id == "base")
    assert base.phases
    assert base.phases[0].duration_days > 0


def test_list_wealth_regimes_has_returns_and_vols() -> None:
    items = list_wealth_regimes()
    assert items
    for r in items:
        assert r.returns_by_type
        assert r.vols_by_type
        assert r.description


# ── Sector stress ────────────────────────────────────────────────────────────


def test_run_sector_stress_with_named_preset() -> None:
    result = run_sector_stress(DEMO, PORTFOLIO, scenario_id="2008 Financial Crisis")
    assert result.portfolio_name == PORTFOLIO
    assert result.base_value > 0
    assert result.new_value < result.base_value  # 2008 should hurt
    assert result.total_change_usd < 0
    assert result.rows


def test_run_sector_stress_with_custom_shocks_only() -> None:
    result = run_sector_stress(
        DEMO, PORTFOLIO,
        custom_sector_shocks={k: -0.5 for k in ("technology", "healthcare", "energy")},
    )
    assert result.total_change_pct < 0


def test_run_sector_stress_custom_overrides_named_scenario() -> None:
    """Custom shocks should patch in on top of a named scenario base."""
    base = run_sector_stress(DEMO, PORTFOLIO, scenario_id="2008 Financial Crisis")
    patched = run_sector_stress(
        DEMO, PORTFOLIO,
        scenario_id="2008 Financial Crisis",
        custom_sector_shocks={"technology": +0.50},  # bull on tech
    )
    assert patched.new_value > base.new_value


def test_run_sector_stress_unknown_scenario_raises() -> None:
    with pytest.raises(ValueError):
        run_sector_stress(DEMO, PORTFOLIO, scenario_id="not-a-real-scenario")


def test_run_sector_stress_no_shocks_at_all_raises() -> None:
    with pytest.raises(ValueError, match="No shocks"):
        run_sector_stress(DEMO, PORTFOLIO)


def test_run_sector_stress_unknown_portfolio_raises() -> None:
    with pytest.raises(ValueError):
        run_sector_stress(DEMO, "does-not-exist", scenario_id="2008 Financial Crisis")


def test_stress_result_to_dataframe_has_legacy_columns() -> None:
    result = run_sector_stress(DEMO, PORTFOLIO, scenario_id="2008 Financial Crisis")
    df = stress_result_to_dataframe(result)
    for col in ("Ticker", "Type", "Base Value", "Shock %", "New Value", "Change $", "Source"):
        assert col in df.columns

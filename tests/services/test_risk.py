"""Tests for risk metrics and the Monte Carlo projection.

The important property is that a corrupted price cannot quietly inflate the
numbers. A single round-trip glitch moved the live portfolio's fitted return
from 9.9% to 35.6% a year, which is the difference between a usable screen
and a dangerously wrong one.
"""

import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.services import risk
from src.services._db import reset_db_cache

ROOT_SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def _clean():
    reset_db_cache()
    yield
    reset_db_cache()


@pytest.fixture
def data_dir(tmp_path):
    dest = tmp_path / "data"
    shutil.copytree("data_demo", dest)
    return str(dest)


def _series(values, start="2022-01-03"):
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


# ── Anomaly detection ────────────────────────────────────────────────────


def test_round_trip_glitch_is_flagged():
    """Price collapses then returns days later — a bad quote, not a return."""
    s = _series([100.0] * 20 + [30.0, 30.0] + [101.0] * 20)
    bad = risk._round_trip_anomalies(s)
    assert len(bad) >= 1
    assert s.index[20] in bad


def test_genuine_crash_is_not_flagged():
    """A real fall that never recovers must stay in the sample."""
    s = _series([100.0] * 20 + [45.0] * 30)
    assert len(risk._round_trip_anomalies(s)) == 0


def test_ordinary_volatility_is_not_flagged():
    rng = np.random.default_rng(1)
    s = _series(100 * np.cumprod(1 + rng.normal(0.0004, 0.01, 300)))
    assert len(risk._round_trip_anomalies(s)) == 0


def test_glitch_does_not_inflate_fitted_return(data_dir, tmp_path):
    """The regression this whole guard exists for."""
    idx = pd.date_range("2022-01-03", periods=600, freq="B")
    clean = pd.Series(100 * np.cumprod(np.full(len(idx), 1.0003)), index=idx)

    corrupted = clean.copy()
    corrupted.iloc[300:302] = corrupted.iloc[299] / 4  # collapse, then recover

    for name, series in (("CLEAN", clean), ("GLITCH", corrupted)):
        series.rename("price").rename_axis("date").to_frame().to_parquet(
            os.path.join(data_dir, "prices", f"{name}.parquet"))

    rets, notes = risk._daily_returns(data_dir, ["CLEAN", "GLITCH"])
    assert any("GLITCH" in n for n in notes)
    # With the glitch excluded the two series must fit almost identically.
    assert rets["GLITCH"].mean() == pytest.approx(rets["CLEAN"].mean(), abs=2e-4)


# ── Metrics ──────────────────────────────────────────────────────────────


def test_metrics_have_sane_signs(data_dir):
    rep = risk.get_risk(data_dir, years=5, num_simulations=200)
    m = rep.metrics
    assert m.annualised_volatility >= 0
    assert m.historical_var_95 <= 0, "VaR is a loss and must be negative"
    assert m.max_drawdown <= 0
    assert m.worst_day <= m.best_day
    assert m.observations > 0


def test_metrics_are_plausible_for_a_diversified_book(data_dir):
    """Guards against the corrupted-price failure mode reappearing."""
    rep = risk.get_risk(data_dir, years=5, num_simulations=200)
    assert rep.metrics.annualised_volatility < 1.0, "vol above 100% signals bad prices"
    assert abs(rep.projection.assumed_annual_return) < 0.75


# ── Projection ───────────────────────────────────────────────────────────


def test_bands_are_aligned_and_ordered(data_dir):
    rep = risk.get_risk(data_dir, years=10, num_simulations=500)
    b = rep.projection.bands
    n = len(b.dates)
    assert all(len(x) == n for x in (b.p5, b.p25, b.p50, b.p75, b.p95))
    for i in range(n):
        assert b.p5[i] <= b.p25[i] <= b.p50[i] <= b.p75[i] <= b.p95[i]


def test_bands_start_at_current_value(data_dir):
    rep = risk.get_risk(data_dir, years=5, num_simulations=200)
    b = rep.projection.bands
    assert b.p50[0] == pytest.approx(rep.market_value, rel=1e-6)


def test_projection_never_goes_negative(data_dir):
    """A normal shock can push a path below zero; a portfolio cannot follow."""
    rep = risk.get_risk(data_dir, years=30, num_simulations=500)
    assert min(rep.projection.bands.p5) >= 0


def test_probability_of_success_is_a_fraction(data_dir):
    rep = risk.get_risk(data_dir, years=10, goal_amount=1.0, num_simulations=200)
    assert rep.projection.probability_of_success is not None
    assert 0.0 <= rep.projection.probability_of_success <= 1.0


def test_unreachable_goal_reports_near_zero(data_dir):
    rep = risk.get_risk(data_dir, years=1, goal_amount=1e12, num_simulations=200)
    assert rep.projection.probability_of_success == 0.0


def test_no_goal_means_no_probability(data_dir):
    rep = risk.get_risk(data_dir, years=5, num_simulations=200)
    assert rep.projection.probability_of_success is None


def test_contributions_raise_the_median(data_dir):
    without = risk.get_risk(data_dir, years=10, num_simulations=800)
    with_ = risk.get_risk(data_dir, years=10, monthly_contribution=1000, num_simulations=800)
    assert with_.projection.final_percentiles["p50"] > without.projection.final_percentiles["p50"]
    assert with_.projection.total_contributions == pytest.approx(1000 * 10 * 12)


def test_results_are_reproducible(data_dir):
    a = risk.get_risk(data_dir, years=5, num_simulations=300)
    b = risk.get_risk(data_dir, years=5, num_simulations=300)
    assert a.projection.final_percentiles == b.projection.final_percentiles


@pytest.mark.parametrize("kwargs", [
    {"years": 0},
    {"years": 100},
    {"num_simulations": 10},
    {"num_simulations": 999999},
    {"monthly_contribution": -50},
])
def test_out_of_range_parameters_are_rejected(data_dir, kwargs):
    with pytest.raises(ValueError):
        risk.get_risk(data_dir, **kwargs)


# ── The shared simulation engine ─────────────────────────────────────────
#
# `simulate_paths` is driven by both this service and the agent's wealth
# skills. It replaced two hand-rolled copies in `wealth_skills.py`, and the
# replacement was verified to be byte-identical across eight scenarios
# including one-time shocks. These tests keep the contract those callers
# depend on — above all the RNG draw order, which is what makes results
# reproducible across the two.


def test_simulation_is_deterministic_for_a_seed():
    kwargs = dict(start_value=1000.0, num_simulations=200, total_days=60,
                  daily_params=lambda _d: (0.0004, 0.01))
    a, _, _ = risk.simulate_paths(**kwargs)
    b, _, _ = risk.simulate_paths(**kwargs)
    assert np.array_equal(a, b)


def test_daily_params_are_read_per_day():
    """A regime that changes partway must actually change the outcome."""
    flat, _, _ = risk.simulate_paths(
        start_value=1000.0, num_simulations=300, total_days=100,
        daily_params=lambda _d: (0.0, 0.01))
    regime, _, _ = risk.simulate_paths(
        start_value=1000.0, num_simulations=300, total_days=100,
        daily_params=lambda d: (0.0, 0.01) if d < 50 else (-0.002, 0.01))
    assert regime.mean() < flat.mean()


def test_one_time_shock_is_applied_once_on_its_day():
    base, _, _ = risk.simulate_paths(
        start_value=1000.0, num_simulations=200, total_days=30,
        daily_params=lambda _d: (0.0, 1e-9))
    shocked, _, _ = risk.simulate_paths(
        start_value=1000.0, num_simulations=200, total_days=30,
        daily_params=lambda _d: (0.0, 1e-9),
        shock_for_day=lambda d: -0.10 if d == 10 else 0.0)
    # With volatility ~0 the only difference is the single 10% haircut.
    assert shocked.mean() == pytest.approx(base.mean() * 0.90, rel=1e-3)


def test_contributions_are_added_monthly():
    """21 trading days per contribution, with drift and vol switched off."""
    finals, _, _ = risk.simulate_paths(
        start_value=0.0, num_simulations=10, total_days=21 * 6,
        daily_params=lambda _d: (0.0, 1e-12), monthly_contribution=100.0)
    assert finals.mean() == pytest.approx(600.0, rel=1e-6)


def test_checkpoints_include_day_zero_and_the_horizon():
    _, days, bands = risk.simulate_paths(
        start_value=1000.0, num_simulations=100, total_days=100,
        daily_params=lambda _d: (0.0, 0.01), checkpoint_every=25)
    assert days[0] == 0 and days[-1] == 100
    assert all(len(v) == len(days) for v in bands.values())
    assert bands[50][0] == pytest.approx(1000.0)


def test_wealth_skills_use_the_shared_engine():
    """Guards against a third copy of the simulation reappearing."""
    source = (ROOT_SRC / "agent" / "wealth_skills.py").read_text()
    assert "simulate_paths" in source
    assert "paths = np.zeros" not in source, "a hand-rolled simulation is back"

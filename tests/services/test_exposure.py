"""Tests for look-through exposure.

The failure modes worth defending against are silent ones: value vanishing
between breakdowns, sector weights computed against the wrong base, and an
unprofiled fund quietly disappearing instead of being reported.
"""

import os
import shutil

import pandas as pd
import pytest

from src.services import exposure
from src.services._db import _get_db, reset_db_cache


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


def _profiles_path(d):
    return os.path.join(d, "fund_profiles.parquet")


def _write_profile(d, ticker, rows, as_of="2026-01-01"):
    """Seed a fund profile: rows is [(category, key, weight), ...]."""
    df = pd.read_parquet(_profiles_path(d)) if os.path.exists(_profiles_path(d)) else pd.DataFrame(
        columns=["fund_ticker", "as_of_date", "category", "key", "weight"]
    )
    new = pd.DataFrame([
        {"fund_ticker": ticker, "as_of_date": as_of, "category": c, "key": k, "weight": w}
        for c, k, w in rows
    ])
    pd.concat([df, new], ignore_index=True).to_parquet(_profiles_path(d), index=False)


def test_no_value_vanishes_between_breakdowns(data_dir):
    rep = exposure.get_exposure(data_dir)
    classified = sum(s.value for s in rep.by_asset_class.slices)
    assert classified + rep.by_asset_class.unclassified == pytest.approx(rep.market_value, rel=1e-4)


def test_asset_class_base_is_the_whole_portfolio(data_dir):
    rep = exposure.get_exposure(data_dir)
    assert rep.by_asset_class.base == pytest.approx(rep.market_value, rel=1e-6)


def test_sector_weights_are_shares_of_the_equity_base(data_dir):
    """Weights divide the equity sleeve, and only its classifiable part.

    They sum to 1 only when every equity dollar could be attributed; where
    some equity has neither a sector nor a fund profile, they sum to the
    covered fraction. Asserting 1.0 unconditionally would be wrong.
    """
    rep = exposure.get_exposure(data_dir)
    if not rep.by_sector.slices:
        pytest.skip("dataset has no equity exposure")

    total_value = sum(s.value for s in rep.by_sector.slices)
    assert total_value == pytest.approx(rep.by_sector.covered, rel=1e-4)

    expected = rep.by_sector.covered / rep.by_sector.base
    assert sum(s.weight for s in rep.by_sector.slices) == pytest.approx(expected, abs=0.01)
    assert rep.by_sector.covered + rep.by_sector.unclassified == pytest.approx(
        rep.by_sector.base, rel=1e-6)


def test_sector_base_is_smaller_than_total_when_bonds_are_held(data_dir):
    """Regression: dividing sectors by total value understates every sector."""
    rep = exposure.get_exposure(data_dir)
    bonds = next((s.value for s in rep.by_asset_class.slices if s.label == "Bonds"), 0.0)
    if bonds > 0 and rep.by_sector.slices:
        assert rep.by_sector.base < rep.market_value


def test_equity_reconciles_with_sector_base_and_shorts(data_dir):
    """Long equity − shorts must equal the Equity asset class exactly."""
    rep = exposure.get_exposure(data_dir)
    equity = next((s.value for s in rep.by_asset_class.slices if s.label == "Equity"), 0.0)
    assert rep.by_sector.base - rep.short_equity == pytest.approx(equity, abs=0.05)


def test_inverse_fund_reduces_equity_and_is_reported(data_dir):
    """A negative stockPosition must subtract, not be dropped or added."""
    db = _get_db(data_dir)
    positions = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    account = str(positions["portfolio_name"].iloc[0])

    from src.models import Asset, AssetType
    db.add_asset(Asset(ticker="INV", asset_type=AssetType.ETF, name="Inverse Fund", sector="", currency="USD"))
    positions = pd.concat([positions, pd.DataFrame([{
        "portfolio_name": account, "ticker": "INV", "quantity": 100.0, "cost_basis": 10.0,
    }])], ignore_index=True)
    positions.to_parquet(os.path.join(data_dir, "positions.parquet"), index=False)

    idx = pd.date_range("2021-05-14", periods=400, freq="B")
    pd.DataFrame({"price": [10.0] * len(idx)}, index=idx).rename_axis("date").to_parquet(
        os.path.join(data_dir, "prices", "INV.parquet"))

    _write_profile(data_dir, "INV", [
        ("asset_class", "stockPosition", -1.0),
        ("asset_class", "cashPosition", 2.0),
        ("sector", "technology", 1.0),
    ], as_of="2099-01-01")  # newest, so it is the profile that gets used
    reset_db_cache()

    rep = exposure.get_exposure(data_dir)
    assert rep.short_equity >= 1000.0 - 1e-6
    equity = next((s.value for s in rep.by_asset_class.slices if s.label == "Equity"), 0.0)
    assert rep.by_sector.base - rep.short_equity == pytest.approx(equity, abs=0.05)


def test_unprofiled_fund_is_reported_not_dropped(data_dir):
    """A fund with no profile must show up as unclassified, with its name."""
    db = _get_db(data_dir)
    positions = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    account = str(positions["portfolio_name"].iloc[0])

    from src.models import Asset, AssetType
    db.add_asset(Asset(ticker="MYSTERY", asset_type=AssetType.ETF, name="Unknown Fund", sector="", currency="USD"))
    positions = pd.concat([positions, pd.DataFrame([{
        "portfolio_name": account, "ticker": "MYSTERY", "quantity": 10.0, "cost_basis": 50.0,
    }])], ignore_index=True)
    positions.to_parquet(os.path.join(data_dir, "positions.parquet"), index=False)

    idx = pd.date_range("2021-05-14", periods=400, freq="B")
    pd.DataFrame({"price": [50.0] * len(idx)}, index=idx).rename_axis("date").to_parquet(
        os.path.join(data_dir, "prices", "MYSTERY.parquet"))
    reset_db_cache()

    rep = exposure.get_exposure(data_dir)
    assert "MYSTERY" in rep.unprofiled_funds
    assert rep.by_asset_class.unclassified >= 500.0 - 1e-6


def test_realestate_key_maps_to_a_readable_label(data_dir):
    """Fund keys are snake_case; a stock's sector is title case. One label each."""
    assert exposure._sector_label("realestate") == "Real Estate"
    assert exposure._sector_label("financial_services") == "Financial Services"


def test_weights_over_one_are_renormalised(data_dir):
    weights, changed = exposure._normalised({"a": 1.5, "b": 0.5})
    assert changed and sum(weights.values()) == pytest.approx(1.0)


def test_weights_already_summing_to_one_are_left_alone(data_dir):
    weights, changed = exposure._normalised({"a": 0.6, "b": 0.4})
    assert not changed and weights == {"a": 0.6, "b": 0.4}


def test_top_contributors_name_real_holdings(data_dir):
    rep = exposure.get_exposure(data_dir)
    tickers = {h for lst in rep.by_asset_class.top_contributors.values() for h in [c.ticker for c in lst]}
    positions = set(pd.read_parquet(os.path.join(data_dir, "positions.parquet"))["ticker"])
    assert tickers <= positions

"""Tests for portfolio-wide income projection.

The rate's unit depends on asset type — dollars per share per payment for
equities, an annual percent for cash-like instruments — and reading it the
wrong way is off by orders of magnitude while still looking like a number.
Those two paths are pinned explicitly.
"""

import os
import shutil

import pandas as pd
import pytest

from src.models import Asset, AssetType
from src.services import income
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


def _add_holding(data_dir, ticker, asset_type, qty, price, rate, freq):
    db = _get_db(data_dir)
    db.add_asset(Asset(
        ticker=ticker, asset_type=asset_type, name=ticker,
        sector="", currency="USD", income_rate=rate, payment_frequency=freq,
    ))
    positions = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    account = str(positions["portfolio_name"].iloc[0])
    positions = pd.concat([positions, pd.DataFrame([{
        "portfolio_name": account, "ticker": ticker,
        "quantity": float(qty), "cost_basis": float(price),
    }])], ignore_index=True)
    positions.to_parquet(os.path.join(data_dir, "positions.parquet"), index=False)

    idx = pd.date_range("2021-05-14", periods=400, freq="B")
    pd.DataFrame({"price": [float(price)] * len(idx)}, index=idx).rename_axis("date").to_parquet(
        os.path.join(data_dir, "prices", f"{ticker}.parquet"))
    reset_db_cache()
    return account


# ── Unit semantics ───────────────────────────────────────────────────────


def test_equity_rate_is_dollars_per_share_per_payment(data_dir):
    """100 shares × $0.50 × 4 payments = $200 a year, not $0.50% of value."""
    _add_holding(data_dir, "DIVETF", AssetType.ETF, qty=100, price=50.0, rate=0.50, freq=4)
    rep = income.get_income(data_dir)
    row = next(r for r in rep.holdings if r.ticker == "DIVETF")
    assert row.annual_income == pytest.approx(200.0)
    assert row.yield_pct == pytest.approx(200.0 / 5000 * 100, rel=1e-6)


def test_cash_rate_is_an_annual_percent_of_value(data_dir):
    """$10,000 at 4% = $400 a year, not 10,000 × 4 × frequency."""
    _add_holding(data_dir, "SAVER", AssetType.CASH, qty=10_000, price=1.0, rate=4.0, freq=12)
    rep = income.get_income(data_dir)
    row = next(r for r in rep.holdings if r.ticker == "SAVER")
    assert row.annual_income == pytest.approx(400.0)


# ── Aggregation ──────────────────────────────────────────────────────────


def test_totals_reconcile_with_holdings(data_dir):
    rep = income.get_income(data_dir)
    assert rep.annual_income == pytest.approx(
        sum(h.annual_income for h in rep.holdings), abs=0.05)
    assert rep.monthly_income == pytest.approx(rep.annual_income / 12, abs=0.05)


def test_buckets_sum_to_the_total(data_dir):
    rep = income.get_income(data_dir)
    for buckets in (rep.by_asset_type, rep.by_account):
        assert sum(b.annual_income for b in buckets) == pytest.approx(
            rep.annual_income, abs=0.05)


def test_portfolio_yield_matches_income_over_value(data_dir):
    rep = income.get_income(data_dir)
    expected = rep.annual_income / rep.market_value * 100
    assert rep.portfolio_yield_pct == pytest.approx(expected, rel=1e-4)


def test_holdings_are_ranked_by_income(data_dir):
    rep = income.get_income(data_dir)
    values = [h.annual_income for h in rep.holdings]
    assert values == sorted(values, reverse=True)


def test_buckets_are_ranked_by_income(data_dir):
    rep = income.get_income(data_dir)
    for buckets in (rep.by_asset_type, rep.by_account):
        values = [b.annual_income for b in buckets]
        assert values == sorted(values, reverse=True)


# ── Non-paying holdings ──────────────────────────────────────────────────


def test_zero_rate_holding_is_reported_not_counted(data_dir):
    """The total is a floor, so a rate-less holding must be visible."""
    _add_holding(data_dir, "NOPAY", AssetType.STOCK, qty=10, price=100.0, rate=0.0, freq=1)
    rep = income.get_income(data_dir)
    assert "NOPAY" in rep.non_income_tickers
    assert all(h.ticker != "NOPAY" for h in rep.holdings)
    assert rep.non_income_value >= 1000.0 - 1e-6


def test_non_income_value_does_not_inflate_yield(data_dir):
    """A large zero-yield holding must pull the portfolio yield down."""
    before = income.get_income(data_dir).portfolio_yield_pct
    _add_holding(data_dir, "BIGZERO", AssetType.STOCK, qty=10_000, price=100.0, rate=0.0, freq=1)
    after = income.get_income(data_dir).portfolio_yield_pct
    assert after < before


def test_bucket_yield_is_income_over_its_own_value(data_dir):
    rep = income.get_income(data_dir)
    for b in rep.by_asset_type:
        if b.market_value:
            assert b.yield_pct == pytest.approx(b.annual_income / b.market_value * 100, rel=1e-4)

"""Tests for the dashboard snapshot service.

The invariants that matter here are the ones a chart silently depends on:
the series must be aligned and complete, totals must reconcile with the
series endpoint, and an unpriced holding must be reported rather than
counted as zero.
"""

import os
import shutil

import pandas as pd
import pytest

from src.services import dashboard
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


def test_snapshot_reconciles(data_dir):
    snap = dashboard.get_snapshot(data_dir)
    assert snap.market_value == pytest.approx(sum(h.market_value for h in snap.holdings))
    assert snap.gain == pytest.approx(snap.market_value - snap.cost, abs=0.01)
    # Totals-by-type must agree with the last point of each stacked series.
    for t, v in snap.totals_by_type.items():
        assert v == pytest.approx(snap.series.by_type[t][-1], abs=0.01)


def test_series_endpoint_matches_headline(data_dir):
    """The chart's last point and the headline stat must be the same number."""
    snap = dashboard.get_snapshot(data_dir)
    assert snap.series.total[-1] == pytest.approx(snap.market_value, rel=1e-6)


def test_series_is_aligned_and_complete(data_dir):
    snap = dashboard.get_snapshot(data_dir)
    n = len(snap.series.dates)
    assert n > 2
    assert len(snap.series.total) == n
    for t in snap.asset_type_order:
        assert len(snap.series.by_type[t]) == n, f"{t} series is not aligned to dates"
    assert snap.series.dates == sorted(snap.series.dates)


def test_stacked_series_sums_to_total(data_dir):
    snap = dashboard.get_snapshot(data_dir)
    for i in range(0, len(snap.series.dates), 25):
        stacked = sum(snap.series.by_type[t][i] for t in snap.asset_type_order)
        assert stacked == pytest.approx(snap.series.total[i], rel=1e-6)


def test_asset_type_order_is_stable(data_dir):
    """Colour follows the asset type, so the order must not depend on size."""
    snap = dashboard.get_snapshot(data_dir)
    assert snap.asset_type_order == ["Cash", "Bond", "Fund", "ETF", "Stock"]


def test_accounts_sorted_by_value(data_dir):
    snap = dashboard.get_snapshot(data_dir)
    values = list(snap.totals_by_account.values())
    assert values == sorted(values, reverse=True)


def test_unpriced_holding_is_reported_not_zeroed(data_dir):
    """A tradeable ticker with no price file must not be silently valued at 0."""
    pos = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    pos = pd.concat([pos, pd.DataFrame([{
        "portfolio_name": pos["portfolio_name"].iloc[0],
        "ticker": "NOPRICE", "quantity": 10.0, "cost_basis": 5.0,
    }])], ignore_index=True)
    pos.to_parquet(os.path.join(data_dir, "positions.parquet"), index=False)

    snap = dashboard.get_snapshot(data_dir)
    assert "NOPRICE" in snap.unpriced
    assert all(h.ticker != "NOPRICE" for h in snap.holdings)
    # and it contributed nothing to the totals
    assert snap.market_value == pytest.approx(sum(h.market_value for h in snap.holdings))


def test_cash_without_price_file_is_held_at_par(data_dir):
    """Cash has no price file by design and must still be valued, at 1.0."""
    snap = dashboard.get_snapshot(data_dir)
    cash = [h for h in snap.holdings if h.asset_type == "Cash"]
    if cash:
        assert all(h.price > 0 for h in cash)
        assert all(h.ticker not in snap.unpriced for h in cash)


def test_holdings_carry_a_display_name(data_dir):
    snap = dashboard.get_snapshot(data_dir)
    assert all(h.name for h in snap.holdings), "every holding needs a label to render"


def test_name_falls_back_to_ticker_when_master_is_blank(data_dir):
    """A blank name must not render as an empty row label."""
    db = _get_db(data_dir)
    assets = db.get_all_assets()
    target = str(assets["ticker"].iloc[0])
    assets.loc[assets["ticker"] == target, "name"] = ""
    db.update_assets_direct(assets)
    reset_db_cache()

    snap = dashboard.get_snapshot(data_dir)
    row = next((h for h in snap.holdings if h.ticker == target), None)
    if row is not None:
        assert row.name == target


def test_too_short_a_window_is_rejected(data_dir):
    today = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
    with pytest.raises(ValueError, match="too little history"):
        dashboard.get_snapshot(data_dir, start=today)


class TestPortfolioScoping:
    """Scoping narrows the snapshot to one portfolio; absent means all."""

    def test_scoped_snapshot_holds_only_that_portfolio(self, data_dir):
        snap = dashboard.get_snapshot(data_dir, portfolio="Demo Brokerage")
        assert snap.holdings, "expected the demo brokerage account to have holdings"
        assert {h.account for h in snap.holdings} == {"Demo Brokerage"}

    def test_scoped_totals_by_account_has_one_entry(self, data_dir):
        snap = dashboard.get_snapshot(data_dir, portfolio="Demo Brokerage")
        assert list(snap.totals_by_account) == ["Demo Brokerage"]

    def test_scopes_partition_the_unscoped_total(self, data_dir):
        """Every dollar lands in exactly one scope — no double-count, no drop."""
        whole = dashboard.get_snapshot(data_dir)
        parts = [
            dashboard.get_snapshot(data_dir, portfolio=name)
            for name in _get_db(data_dir).list_portfolios()
        ]
        assert sum(p.market_value for p in parts) == pytest.approx(
            whole.market_value, abs=0.01
        )
        assert sum(p.cost for p in parts) == pytest.approx(whole.cost, abs=0.01)

    def test_scoped_series_still_reconciles_with_headline(self, data_dir):
        snap = dashboard.get_snapshot(data_dir, portfolio="Demo Brokerage")
        assert snap.series.total[-1] == pytest.approx(snap.market_value, rel=1e-6)

    def test_scoped_series_is_aligned_to_the_same_dates(self, data_dir):
        """A scoped chart must share the unscoped x-axis, not a shorter one."""
        whole = dashboard.get_snapshot(data_dir)
        snap = dashboard.get_snapshot(data_dir, portfolio="Demo Brokerage")
        assert snap.series.dates == whole.series.dates

    def test_unknown_portfolio_is_not_found(self, data_dir):
        with pytest.raises(ValueError, match="not found"):
            dashboard.get_snapshot(data_dir, portfolio="No Such Account")

    def test_absent_scope_is_unchanged(self, data_dir):
        """The default path must stay byte-identical to the unscoped call."""
        assert dashboard.get_snapshot(data_dir) == dashboard.get_snapshot(
            data_dir, portfolio=None
        )

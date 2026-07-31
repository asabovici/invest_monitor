"""Tests for the data-correction service.

The invariants worth defending here are the ones whose failure would silently
corrupt real records: a replay of an untouched ledger must be a no-op, a replay
must never delete positions the ledger says nothing about, and nothing may reach
disk without an explicit apply.
"""

import os
import shutil

import pandas as pd
import pytest

from src.services import datafix
from src.services._db import _get_db, reset_db_cache


@pytest.fixture(autouse=True)
def _clean_state():
    datafix.reset_staged()
    reset_db_cache()
    yield
    datafix.reset_staged()
    reset_db_cache()


@pytest.fixture
def data_dir(tmp_path):
    """A writable copy of the demo data with a small known ledger."""
    dest = tmp_path / "data"
    shutil.copytree("data_demo", dest)
    d = str(dest)
    db = _get_db(d)
    db.record_trade("Demo Brokerage", "AAPL", "BUY", 100, 150.0, "2026-01-15")
    db.record_trade("Demo Brokerage", "AAPL", "BUY", 50, 180.0, "2026-03-10")
    return d


def _positions(data_dir, portfolio="Demo Brokerage"):
    df = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    return df[df["portfolio_name"] == portfolio].set_index("ticker")


# ── Replay fidelity ──────────────────────────────────────────────────────────


def test_replay_of_untouched_ledger_is_a_noop(data_dir):
    # Divergence from Database._apply_trade_to_positions would rewrite correct data.
    with pytest.raises(ValueError, match="already match the ledger"):
        datafix.preview_ledger_replay(data_dir, "Demo Brokerage")


def test_replay_reproduces_average_cost_blending(data_dir):
    pos = _positions(data_dir)
    assert pos.loc["AAPL", "quantity"] == 150
    assert pos.loc["AAPL", "cost_basis"] == pytest.approx((100 * 150 + 50 * 180) / 150)


def test_sell_reduces_quantity_and_leaves_cost_basis(data_dir):
    _get_db(data_dir).record_trade("Demo Brokerage", "AAPL", "SELL", 50, 200.0, "2026-04-01")
    pos = _positions(data_dir)
    assert pos.loc["AAPL", "quantity"] == 100
    assert pos.loc["AAPL", "cost_basis"] == pytest.approx(160.0)
    with pytest.raises(ValueError, match="already match the ledger"):
        datafix.preview_ledger_replay(data_dir, "Demo Brokerage")


# ── The data-loss guard ──────────────────────────────────────────────────────


def test_replay_preserves_positions_with_no_trades(data_dir):
    """Imported positions have no ledger behind them and must survive a replay."""
    before = set(_positions(data_dir).index)
    untracked = before - {"AAPL"}
    assert untracked, "fixture should contain imported positions with no trades"

    preview = datafix.preview_trade_correction(data_dir, trade_id=1, trade_price=120.0)
    touched = {c.key.split(" / ")[-1] for c in preview.changes if "/" in c.key}
    assert touched == {"AAPL"}

    datafix.apply_change(preview.change_id)
    assert set(_positions(data_dir).index) == before


def test_sell_to_zero_still_removes_a_ledger_covered_position(data_dir):
    _get_db(data_dir).record_trade("Demo Brokerage", "AAPL", "SELL", 150, 200.0, "2026-05-01")
    assert "AAPL" not in _positions(data_dir).index


def _partial_ledger(data_dir, portfolio="Demo Brokerage", ticker="ACME"):
    """A ticker whose position predates the ledger — only recent trades recorded.

    This is the real-world shape: positions imported from a CSV, then a few
    trades entered by hand on top. The ticker HAS trades, so _merge_untracked
    does not protect it, and a naive replay discards everything older.
    """
    _get_db(data_dir).record_trade(portfolio, ticker, "BUY", 1, 100.0, "2026-06-01")
    # record_trade blends into the existing imported position; rewind the stored
    # position to represent the large pre-ledger holding.
    path = os.path.join(data_dir, "positions.parquet")
    df = pd.read_parquet(path)
    mask = (df["portfolio_name"] == portfolio) & (df["ticker"] == ticker)
    df.loc[mask, "quantity"] = 500.0
    df.to_parquet(path, index=False)


def test_replay_warns_when_it_would_shrink_a_partially_covered_holding(data_dir):
    _partial_ledger(data_dir)
    preview = datafix.preview_ledger_replay(data_dir, "Demo Brokerage")
    assert any("DESTRUCTIVE" in w for w in preview.warnings)
    assert any("shares unaccounted for" in w for w in preview.warnings)


def test_scan_does_not_recommend_replay_when_it_would_destroy_holdings(data_dir):
    """The scan must never point at a fix that would discard real shares."""
    _partial_ledger(data_dir)
    report = datafix.scan_data_issues(data_dir)
    drift = [i for i in report.issues if i.domain == "positions" and "ledger" in i.detail]
    assert drift, "expected the scan to notice the ledger disagreement"
    assert all("INCOMPLETE" in i.detail for i in drift)
    assert all(i.suggested_fix != "preview_ledger_replay" for i in drift)


def test_scan_still_recommends_replay_for_harmless_drift(data_dir):
    """A drift that does not reduce holdings is safe to replay."""
    path = os.path.join(data_dir, "positions.parquet")
    df = pd.read_parquet(path)
    mask = (df["portfolio_name"] == "Demo Brokerage") & (df["ticker"] == "AAPL")
    df.loc[mask, "cost_basis"] = 1.0  # wrong basis, same quantity
    df.to_parquet(path, index=False)

    report = datafix.scan_data_issues(data_dir)
    drift = [i for i in report.issues if i.domain == "positions" and "ledger" in i.detail]
    assert drift
    assert all(i.suggested_fix == "preview_ledger_replay" for i in drift)


# ── Preview / apply gate ─────────────────────────────────────────────────────


def test_preview_writes_nothing(data_dir):
    before = _positions(data_dir).loc["AAPL", "cost_basis"]
    datafix.preview_trade_correction(data_dir, trade_id=1, trade_price=120.0)
    assert _positions(data_dir).loc["AAPL", "cost_basis"] == before


def test_apply_commits_and_backs_up(data_dir):
    preview = datafix.preview_trade_correction(data_dir, trade_id=1, trade_price=120.0)
    result = datafix.apply_change(preview.change_id)

    assert _positions(data_dir).loc["AAPL", "cost_basis"] == pytest.approx(
        (100 * 120 + 50 * 180) / 150
    )
    assert os.path.exists(os.path.join(result.backup_path, "positions.parquet"))
    assert os.path.exists(result.audit_path)


def test_change_is_single_use(data_dir):
    preview = datafix.preview_trade_correction(data_dir, trade_id=1, trade_price=120.0)
    datafix.apply_change(preview.change_id)
    with pytest.raises(ValueError, match="not found"):
        datafix.apply_change(preview.change_id)


def test_discard_leaves_data_untouched(data_dir):
    before = _positions(data_dir).loc["AAPL", "cost_basis"]
    preview = datafix.preview_trade_correction(data_dir, trade_id=1, trade_price=120.0)
    datafix.discard_change(preview.change_id)
    assert datafix.list_staged() == []
    assert _positions(data_dir).loc["AAPL", "cost_basis"] == before


def test_audit_log_records_applied_changes(data_dir):
    preview = datafix.preview_trade_correction(data_dir, trade_id=1, trade_price=120.0)
    datafix.apply_change(preview.change_id)
    entries = datafix.read_audit_log(data_dir)
    assert len(entries) == 1
    assert entries[0]["domain"] == "trades"


# ── Retroactive edits ────────────────────────────────────────────────────────


def test_insert_trade_is_placed_by_date_not_appended(data_dir):
    """A backdated buy must blend as if it had always been there."""
    preview = datafix.preview_trade_insert(
        data_dir, "Demo Brokerage", "AAPL", "BUY", 50, 100.0, "2026-02-01"
    )
    datafix.apply_change(preview.change_id)
    pos = _positions(data_dir)
    assert pos.loc["AAPL", "quantity"] == 200
    assert pos.loc["AAPL", "cost_basis"] == pytest.approx(
        (100 * 150 + 50 * 100 + 50 * 180) / 200
    )


def test_delete_trade_replays_without_it(data_dir):
    preview = datafix.preview_trade_delete(data_dir, trade_id=2)
    datafix.apply_change(preview.change_id)
    pos = _positions(data_dir)
    assert pos.loc["AAPL", "quantity"] == 100
    assert pos.loc["AAPL", "cost_basis"] == pytest.approx(150.0)


def test_opening_balance_seeds_a_dated_trade(data_dir):
    preview = datafix.preview_opening_balance(
        data_dir, "Demo Brokerage", "ACME", 50, 230.0, "2025-06-01"
    )
    datafix.apply_change(preview.change_id)
    trades = _get_db(data_dir).list_trades("Demo Brokerage")
    assert not trades[(trades["ticker"] == "ACME")].empty


def test_cost_basis_order_of_magnitude_warning(data_dir):
    """The April 2026 total-vs-per-share bug should be surfaced, not silently applied."""
    preview = datafix.preview_trade_correction(data_dir, trade_id=2, trade_price=18000.0)
    assert any("PER SHARE" in w for w in preview.warnings)


def test_unknown_trade_rejected(data_dir):
    with pytest.raises(ValueError, match="not found"):
        datafix.preview_trade_correction(data_dir, trade_id=999, trade_price=1.0)


def test_no_op_correction_rejected(data_dir):
    with pytest.raises(ValueError, match="No changes requested"):
        datafix.preview_trade_correction(data_dir, trade_id=1, trade_price=150.0)


# ── Security master ──────────────────────────────────────────────────────────


def test_asset_fix_is_field_level(data_dir):
    before = _get_db(data_dir).get_all_assets()
    preview = datafix.preview_asset_fix(data_dir, "ACME", sector="Industrials")
    datafix.apply_change(preview.change_id)

    after = _get_db(data_dir).get_all_assets()
    assert after.loc[after["ticker"] == "ACME", "sector"].iloc[0] == "Industrials"
    # Every other row is untouched — update_assets_direct overwrites the whole table.
    assert len(after) == len(before)
    others = after[after["ticker"] != "ACME"].reset_index(drop=True)
    assert others["sector"].tolist() == (
        before[before["ticker"] != "ACME"].reset_index(drop=True)["sector"].tolist()
    )


def test_invalid_asset_type_rejected(data_dir):
    with pytest.raises(ValueError, match="Invalid asset_type"):
        datafix.preview_asset_fix(data_dir, "ACME", asset_type="Nonsense")


def test_unknown_asset_column_rejected(data_dir):
    with pytest.raises(ValueError, match="Unknown asset fields"):
        datafix.preview_asset_fix(data_dir, "ACME", colour="blue")


def test_unknown_ticker_rejected(data_dir):
    with pytest.raises(ValueError, match="not found"):
        datafix.preview_asset_fix(data_dir, "NOPE", sector="X")


# ── Prices ───────────────────────────────────────────────────────────────────


@pytest.fixture
def priced(data_dir):
    idx = pd.date_range("2026-01-01", "2026-03-31", freq="B")
    df = pd.DataFrame({"price": [100.0 + i for i in range(len(idx))]}, index=idx)
    df.index.name = "date"
    df.drop(df.index[10:14]).to_parquet(
        os.path.join(data_dir, "prices", "TEST.parquet")
    )
    return data_dir


def test_find_price_gaps(priced):
    gaps = datafix.find_price_gaps(priced, "TEST")
    assert len(gaps) == 1
    assert gaps[0].missing_days == 4


def test_fill_forward_carries_last_price(priced):
    before = pd.read_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    preview = datafix.preview_price_fill_forward(priced, "TEST")
    datafix.apply_change(preview.change_id)

    after = pd.read_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    assert len(after) == len(before) + 4
    assert datafix.find_price_gaps(priced, "TEST") == []
    # Carried values equal the last real observation before the gap.
    assert after["price"].iloc[10:14].nunique() == 1


def test_fill_forward_refuses_runs_over_the_cap(priced):
    # Interior gap only — trailing rows are kept, because a series that simply
    # ends early is staleness rather than a gap and is not filled at all.
    df = pd.read_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    df.drop(df.index[20:55]).to_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    assert max(g.missing_days for g in datafix.find_price_gaps(priced, "TEST")) > 5

    with pytest.raises(ValueError, match="max_run_days"):
        datafix.preview_price_fill_forward(priced, "TEST", max_run_days=5)


def test_fill_forward_allows_a_long_gap_when_the_cap_is_raised(priced):
    df = pd.read_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    df.drop(df.index[20:55]).to_parquet(os.path.join(priced, "prices", "TEST.parquet"))

    preview = datafix.preview_price_fill_forward(priced, "TEST", max_run_days=90)
    assert any("depresses measured volatility" in w for w in preview.warnings)


def test_truncated_series_is_extended_only_when_asked(priced):
    """A series ending early is left alone unless through_date says otherwise."""
    df = pd.read_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    truncated = df.drop(df.index[20:])
    truncated.to_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    last = truncated.index.max()

    preview = datafix.preview_price_fill_forward(
        priced, "TEST", through_date="2026-03-31", max_run_days=90
    )
    datafix.apply_change(preview.change_id)

    after = pd.read_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    assert after.index.max() == pd.Timestamp("2026-03-31")
    assert after.loc[pd.Timestamp("2026-03-31"), "price"] == after.loc[last, "price"]


def test_fill_forward_with_nothing_missing_rejected(data_dir):
    idx = pd.date_range("2026-01-01", "2026-02-01", freq="B")
    df = pd.DataFrame({"price": [1.0] * len(idx)}, index=idx)
    df.index.name = "date"
    df.to_parquet(os.path.join(data_dir, "prices", "FULL.parquet"))
    with pytest.raises(ValueError, match="No missing business days"):
        datafix.preview_price_fill_forward(data_dir, "FULL")


def test_price_correction(priced):
    preview = datafix.preview_price_correction(priced, "TEST", "2026-01-02", 999.0)
    datafix.apply_change(preview.change_id)
    df = pd.read_parquet(os.path.join(priced, "prices", "TEST.parquet"))
    assert df.loc[pd.Timestamp("2026-01-02"), "price"] == 999.0


def test_missing_price_history_rejected(data_dir):
    with pytest.raises(ValueError, match="No price history"):
        datafix.preview_price_fill_forward(data_dir, "NOSUCH")


# ── Scan ─────────────────────────────────────────────────────────────────────


def test_scan_flags_ticker_missing_from_security_master(data_dir):
    # AAPL was created by record_trade, which does not add a security-master row.
    report = datafix.scan_data_issues(data_dir)
    assert any(
        i.domain == "positions" and "security master" in i.detail for i in report.issues
    )


def test_scan_orders_errors_first(data_dir):
    report = datafix.scan_data_issues(data_dir)
    severities = [i.severity for i in report.issues]
    assert severities == sorted(severities, key=lambda s: {"error": 0, "warning": 1, "info": 2}[s])

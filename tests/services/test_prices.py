"""Tests for src/services/prices.py."""

import sys
import types
from datetime import date

import pandas as pd
import pytest

from src.services.prices import (
    collect_prices,
    get_latest_prices,
    get_price_history,
    price_history_to_dataframe,
)

DEMO = "data_demo"


# ── Reads against the demo dataset ───────────────────────────────────────────


def test_get_latest_prices_returns_values_for_known_tickers() -> None:
    resp = get_latest_prices(DEMO, ["ACME", "BDRK"])
    assert set(resp.prices) == {"ACME", "BDRK"}
    assert resp.prices["ACME"] is not None
    assert resp.prices["BDRK"] is not None
    assert resp.prices["ACME"] > 0


def test_get_latest_prices_empty_tickers_returns_empty_dict() -> None:
    assert get_latest_prices(DEMO, []).prices == {}


def test_get_price_history_aligned_dates_and_prices() -> None:
    history = get_price_history(DEMO, ["ACME"], start=date(2026, 4, 1))
    assert history.tickers == ["ACME"]
    assert history.dates, "expected at least one date"
    assert len(history.prices["ACME"]) == len(history.dates)
    # All dates >= start
    assert min(history.dates) >= date(2026, 4, 1)


def test_get_price_history_unknown_ticker_padded_with_null() -> None:
    """Unknown tickers should be padded to the same length as known ones."""
    history = get_price_history(DEMO, ["ACME", "NEVER_EXISTED"])
    assert "NEVER_EXISTED" in history.prices
    assert len(history.prices["NEVER_EXISTED"]) == len(history.dates)


def test_price_history_to_dataframe_round_trip() -> None:
    history = get_price_history(DEMO, ["ACME", "BDRK"], start=date(2026, 4, 1))
    df = price_history_to_dataframe(history)
    assert list(df.columns) == ["ACME", "BDRK"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) == len(history.dates)


# ── Write path with yfinance monkeypatched ───────────────────────────────────


def _fake_yfinance(returned_df: pd.DataFrame | None = None):
    """Build a minimal `yfinance`-like module exposing `download`."""
    if returned_df is None:
        # Two business days, one Close column — matches what save_prices expects.
        returned_df = pd.DataFrame(
            {"Close": [100.0, 101.0]},
            index=pd.to_datetime(["2026-05-01", "2026-05-02"]),
        )
    module = types.ModuleType("yfinance")

    def download(ticker, period="1y", progress=False, **kwargs):
        return returned_df.copy()

    module.download = download
    return module


def test_collect_prices_uses_yfinance_and_records_success(
    tmp_path, monkeypatch
) -> None:
    data_dir = str(tmp_path)
    # Seed two assets so collect-all has something to fetch.
    from src.database import Database
    from src.models import Asset, AssetType
    db = Database(data_dir)
    db.add_asset(Asset(ticker="AAA", asset_type=AssetType.STOCK, name="A"))
    db.add_asset(Asset(ticker="BBB", asset_type=AssetType.STOCK, name="B"))

    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance())

    result = collect_prices(data_dir, period="1mo")
    assert set(result.tickers_collected) == {"AAA", "BBB"}
    assert result.tickers_failed == {}

    # Prices actually landed in storage.
    latest = get_latest_prices(data_dir, ["AAA", "BBB"])
    assert latest.prices["AAA"] == pytest.approx(101.0)


def test_collect_prices_records_empty_download_as_failure(
    tmp_path, monkeypatch
) -> None:
    data_dir = str(tmp_path)
    from src.database import Database
    from src.models import Asset, AssetType
    db = Database(data_dir)
    db.add_asset(Asset(ticker="GHOST", asset_type=AssetType.STOCK, name="G"))

    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(pd.DataFrame()))

    result = collect_prices(data_dir, period="1mo")
    assert result.tickers_collected == []
    assert "GHOST" in result.tickers_failed


def test_collect_prices_for_unknown_portfolio_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance())
    with pytest.raises(ValueError):
        collect_prices(str(tmp_path), period="1mo", portfolio_name="never-was")

import os
import tempfile
import pandas as pd
import numpy as np
import pytest
from src.models import Asset, AssetType, Constituent, Position, Portfolio
from src.database.database import Database


@pytest.fixture
def db(tmp_path):
    return Database(data_dir=str(tmp_path))


def make_asset(ticker="AAPL", asset_type=AssetType.STOCK, constituents=None):
    return Asset(
        ticker=ticker,
        name=f"{ticker} Inc",
        asset_type=asset_type,
        currency="USD",
        sector="Technology",
        constituents=constituents or [],
    )


def make_prices_df(ticker, dates, prices):
    idx = pd.to_datetime(dates)
    # yfinance returns a MultiIndex column in newer versions; simulate flat Close column
    df = pd.DataFrame({"Close": prices}, index=idx)
    df.index.name = "Date"
    return df


# --- Initialisation ---

def test_init_creates_empty_parquet_files(db, tmp_path):
    assert os.path.exists(os.path.join(str(tmp_path), "assets.parquet"))
    assert os.path.exists(os.path.join(str(tmp_path), "constituents.parquet"))
    assert os.path.isdir(os.path.join(str(tmp_path), "prices"))


def test_init_assets_has_correct_columns(db, tmp_path):
    df = pd.read_parquet(os.path.join(str(tmp_path), "assets.parquet"))
    assert list(df.columns) == ["ticker", "name", "asset_type", "currency", "sector"]
    assert len(df) == 0


# --- add_asset ---

def test_add_asset_persists_row(db, tmp_path):
    db.add_asset(make_asset("AAPL"))
    df = pd.read_parquet(os.path.join(str(tmp_path), "assets.parquet"))
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "AAPL"
    assert df.iloc[0]["asset_type"] == "Stock"


def test_add_asset_upserts_on_duplicate(db, tmp_path):
    db.add_asset(make_asset("AAPL"))
    updated = Asset(ticker="AAPL", name="Apple Updated", asset_type=AssetType.STOCK, currency="USD")
    db.add_asset(updated)
    df = pd.read_parquet(os.path.join(str(tmp_path), "assets.parquet"))
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Apple Updated"


def test_add_multiple_assets(db, tmp_path):
    db.add_asset(make_asset("AAPL"))
    db.add_asset(make_asset("MSFT"))
    df = pd.read_parquet(os.path.join(str(tmp_path), "assets.parquet"))
    assert len(df) == 2


def test_add_asset_with_constituents(db, tmp_path):
    constituents = [Constituent(ticker="AAPL", weight=0.07), Constituent(ticker="MSFT", weight=0.06)]
    db.add_asset(make_asset("SPY", AssetType.ETF, constituents=constituents))
    df = pd.read_parquet(os.path.join(str(tmp_path), "constituents.parquet"))
    assert len(df) == 2
    assert set(df["constituent_ticker"]) == {"AAPL", "MSFT"}


def test_add_asset_replaces_constituents_on_upsert(db, tmp_path):
    c1 = [Constituent(ticker="AAPL", weight=0.07)]
    db.add_asset(make_asset("SPY", AssetType.ETF, constituents=c1))
    c2 = [Constituent(ticker="MSFT", weight=0.05), Constituent(ticker="AMZN", weight=0.04)]
    db.add_asset(make_asset("SPY", AssetType.ETF, constituents=c2))
    df = pd.read_parquet(os.path.join(str(tmp_path), "constituents.parquet"))
    assert set(df["constituent_ticker"]) == {"MSFT", "AMZN"}


# --- get_all_tickers ---

def test_get_all_tickers_empty(db):
    assert db.get_all_tickers() == []


def test_get_all_tickers_returns_added_tickers(db):
    db.add_asset(make_asset("AAPL"))
    db.add_asset(make_asset("MSFT"))
    tickers = db.get_all_tickers()
    assert set(tickers) == {"AAPL", "MSFT"}


# --- save_prices ---

def test_save_prices_creates_file(db, tmp_path):
    df = make_prices_df("AAPL", ["2024-01-01", "2024-01-02"], [150.0, 152.0])
    db.save_prices("AAPL", df)
    assert os.path.exists(os.path.join(str(tmp_path), "prices", "AAPL.parquet"))


def test_save_prices_stores_correct_values(db, tmp_path):
    df = make_prices_df("AAPL", ["2024-01-01", "2024-01-02"], [150.0, 152.0])
    db.save_prices("AAPL", df)
    stored = pd.read_parquet(os.path.join(str(tmp_path), "prices", "AAPL.parquet"))
    assert len(stored) == 2
    assert stored.loc[pd.Timestamp("2024-01-01"), "price"] == 150.0


def test_save_prices_upserts_on_overlap(db, tmp_path):
    df1 = make_prices_df("AAPL", ["2024-01-01", "2024-01-02"], [150.0, 152.0])
    db.save_prices("AAPL", df1)
    # Same dates with different prices — new values should win
    df2 = make_prices_df("AAPL", ["2024-01-02", "2024-01-03"], [999.0, 155.0])
    db.save_prices("AAPL", df2)
    stored = pd.read_parquet(os.path.join(str(tmp_path), "prices", "AAPL.parquet"))
    assert len(stored) == 3
    assert stored.loc[pd.Timestamp("2024-01-02"), "price"] == 999.0


def test_save_prices_independent_per_ticker(db, tmp_path):
    df_aapl = make_prices_df("AAPL", ["2024-01-01"], [150.0])
    df_msft = make_prices_df("MSFT", ["2024-01-01"], [300.0])
    db.save_prices("AAPL", df_aapl)
    db.save_prices("MSFT", df_msft)
    assert os.path.exists(os.path.join(str(tmp_path), "prices", "AAPL.parquet"))
    assert os.path.exists(os.path.join(str(tmp_path), "prices", "MSFT.parquet"))


# --- get_historical_prices ---

def test_get_historical_prices_returns_pivot(db):
    db.save_prices("AAPL", make_prices_df("AAPL", ["2024-01-01", "2024-01-02"], [150.0, 152.0]))
    db.save_prices("MSFT", make_prices_df("MSFT", ["2024-01-01", "2024-01-02"], [300.0, 305.0]))
    result = db.get_historical_prices(["AAPL", "MSFT"])
    assert "AAPL" in result.columns
    assert "MSFT" in result.columns
    assert len(result) == 2


def test_get_historical_prices_filters_by_start_date(db):
    db.save_prices("AAPL", make_prices_df("AAPL", ["2024-01-01", "2024-01-02", "2024-01-03"], [150.0, 152.0, 154.0]))
    result = db.get_historical_prices(["AAPL"], start_date="2024-01-02")
    assert len(result) == 2


def test_get_historical_prices_missing_ticker_skipped(db):
    db.save_prices("AAPL", make_prices_df("AAPL", ["2024-01-01"], [150.0]))
    result = db.get_historical_prices(["AAPL", "NONEXISTENT"])
    assert "AAPL" in result.columns
    assert "NONEXISTENT" not in result.columns


def test_get_historical_prices_all_missing_returns_empty(db):
    result = db.get_historical_prices(["NONEXISTENT"])
    assert result.empty


# --- No sqlite3 references remain ---

def test_no_sqlite3_in_database_module():
    import ast
    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "database", "database.py")
    with open(src_path) as f:
        source = f.read()
    assert "sqlite3" not in source


def test_no_sqlite3_in_collector_module():
    src_path = os.path.join(os.path.dirname(__file__), "..", "src", "collector.py")
    with open(src_path) as f:
        source = f.read()
    assert "sqlite3" not in source

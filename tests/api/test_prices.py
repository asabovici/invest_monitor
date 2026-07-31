"""Tests for /prices HTTP routes via FastAPI TestClient."""

import sys
import types

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api.main import app


DEMO_HEADERS = {"X-Data-Dir": "data_demo"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_latest_prices_demo(client: TestClient) -> None:
    r = client.get("/prices/latest?tickers=ACME,BDRK", headers=DEMO_HEADERS)
    assert r.status_code == 200
    prices = r.json()["prices"]
    assert "ACME" in prices and "BDRK" in prices
    assert isinstance(prices["ACME"], float)
    assert prices["ACME"] > 0


def test_get_latest_prices_no_tickers_400(client: TestClient) -> None:
    r = client.get("/prices/latest?tickers=", headers=DEMO_HEADERS)
    assert r.status_code == 400


def test_get_price_history_demo(client: TestClient) -> None:
    r = client.get(
        "/prices/history?tickers=ACME&start=2026-04-01", headers=DEMO_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tickers"] == ["ACME"]
    assert body["dates"]
    assert len(body["prices"]["ACME"]) == len(body["dates"])


def test_get_price_history_invalid_date_422(client: TestClient) -> None:
    r = client.get(
        "/prices/history?tickers=ACME&start=not-a-date", headers=DEMO_HEADERS,
    )
    assert r.status_code == 422


def test_collect_endpoint_with_mocked_yfinance(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    """POST /prices/collect drives the service with yfinance stubbed."""
    fake = types.ModuleType("yfinance")
    fake.download = lambda *args, **kwargs: pd.DataFrame(
        {"Close": [200.0]}, index=pd.to_datetime(["2026-05-20"]),
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    from src.database import Database
    from src.models import Asset, AssetType
    Database(str(tmp_path)).add_asset(
        Asset(ticker="ZZZ", asset_type=AssetType.STOCK, name="Z"),
    )

    headers = {"X-Data-Dir": str(tmp_path)}
    r = client.post("/prices/collect", json={"period": "1mo"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["tickers_collected"] == ["ZZZ"]


def test_collect_endpoint_unknown_portfolio_404(client: TestClient, tmp_path) -> None:
    headers = {"X-Data-Dir": str(tmp_path)}
    r = client.post(
        "/prices/collect",
        json={"period": "1mo", "portfolio_name": "missing"},
        headers=headers,
    )
    assert r.status_code == 404

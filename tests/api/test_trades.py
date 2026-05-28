"""Tests for /trades + /portfolios/{name}/trades."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def headers(tmp_path) -> dict[str, str]:
    return {"X-Data-Dir": str(tmp_path)}


@pytest.fixture
def seeded(client: TestClient, headers) -> dict[str, str]:
    client.post("/portfolios", json={"name": "P1"}, headers=headers)
    return headers


def _trade(**overrides):
    body = {
        "portfolio_name": "P1",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 10,
        "trade_price": 150,
        "trade_date": "2026-05-01",
    }
    body.update(overrides)
    return body


def test_record_trade_returns_updated_list(client: TestClient, seeded) -> None:
    r = client.post("/trades", json=_trade(), headers=seeded)
    assert r.status_code == 201
    assert r.json()["trades"][0]["ticker"] == "AAPL"


def test_record_trade_unknown_portfolio_404(client: TestClient, headers) -> None:
    r = client.post("/trades", json=_trade(portfolio_name="Ghost"), headers=headers)
    assert r.status_code == 404


def test_record_trade_invalid_side_422(client: TestClient, seeded) -> None:
    r = client.post("/trades", json=_trade(side="HOLD"), headers=seeded)
    assert r.status_code == 422


def test_record_trade_zero_quantity_422(client: TestClient, seeded) -> None:
    r = client.post("/trades", json=_trade(quantity=0), headers=seeded)
    assert r.status_code == 422


def test_list_all_trades(client: TestClient, seeded) -> None:
    client.post("/trades", json=_trade(), headers=seeded)
    r = client.get("/trades", headers=seeded)
    assert r.status_code == 200
    assert len(r.json()["trades"]) == 1


def test_list_trades_filter_by_portfolio(client: TestClient, seeded) -> None:
    client.post("/portfolios", json={"name": "P2"}, headers=seeded)
    client.post("/trades", json=_trade(), headers=seeded)
    client.post("/trades", json=_trade(portfolio_name="P2"), headers=seeded)
    r = client.get("/trades?portfolio_name=P1", headers=seeded)
    assert r.status_code == 200
    assert {t["portfolio_name"] for t in r.json()["trades"]} == {"P1"}


def test_list_trades_filter_unknown_portfolio_404(client: TestClient, headers) -> None:
    assert client.get("/trades?portfolio_name=Ghost", headers=headers).status_code == 404


def test_portfolio_trades_endpoint(client: TestClient, seeded) -> None:
    client.post("/trades", json=_trade(), headers=seeded)
    r = client.get("/portfolios/P1/trades", headers=seeded)
    assert r.status_code == 200
    assert len(r.json()["trades"]) == 1

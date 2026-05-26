"""Tests for /portfolios mutation routes via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def headers(tmp_path) -> dict[str, str]:
    return {"X-Data-Dir": str(tmp_path)}


def test_create_then_get(client: TestClient, headers) -> None:
    r = client.post("/portfolios", json={"name": "P1"}, headers=headers)
    assert r.status_code == 201
    assert r.json()["name"] == "P1"
    assert r.json()["positions"] == []
    r2 = client.get("/portfolios/P1", headers=headers)
    assert r2.status_code == 200


def test_create_duplicate_returns_409(client: TestClient, headers) -> None:
    client.post("/portfolios", json={"name": "Dup"}, headers=headers)
    r = client.post("/portfolios", json={"name": "Dup"}, headers=headers)
    assert r.status_code == 409


def test_create_empty_name_returns_422(client: TestClient, headers) -> None:
    """Pydantic min_length=1 rejects empty before service runs."""
    r = client.post("/portfolios", json={"name": ""}, headers=headers)
    assert r.status_code == 422


def test_delete_returns_204(client: TestClient, headers) -> None:
    client.post("/portfolios", json={"name": "Goner"}, headers=headers)
    r = client.delete("/portfolios/Goner", headers=headers)
    assert r.status_code == 204


def test_delete_missing_returns_404(client: TestClient, headers) -> None:
    r = client.delete("/portfolios/never-was", headers=headers)
    assert r.status_code == 404


def test_load_csv_creates_portfolio(client: TestClient, headers) -> None:
    csv_text = (
        "Ticker,Name,Type,Quantity,CostBasis,Currency,Sector\n"
        "AAPL,Apple Inc,Stock,10,1500,USD,Technology\n"
    )
    r = client.post(
        "/portfolios/load-csv",
        json={"name": "FromCSV", "csv_text": csv_text},
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "FromCSV"
    assert any(p["ticker"] == "AAPL" for p in body["positions"])


def test_update_positions_replaces(client: TestClient, headers) -> None:
    client.post("/portfolios", json={"name": "Editable"}, headers=headers)
    payload = {
        "positions": [
            {
                "ticker": "VTI", "quantity": 10, "cost_basis_per_share": 200.0,
                "asset_type": "ETF", "name": "Vanguard Total Market",
            },
        ],
    }
    r = client.put("/portfolios/Editable/positions", json=payload, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert [p["ticker"] for p in body["positions"]] == ["VTI"]


def test_update_positions_on_missing_returns_404(client: TestClient, headers) -> None:
    r = client.put(
        "/portfolios/missing-xyz/positions",
        json={"positions": []},
        headers=headers,
    )
    assert r.status_code == 404

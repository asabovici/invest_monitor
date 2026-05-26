"""Tests for the /portfolios HTTP routes via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_list_portfolios_demo(client: TestClient) -> None:
    r = client.get("/portfolios", headers=DEMO_HEADERS)
    assert r.status_code == 200
    payload = r.json()
    assert isinstance(payload, list)
    names = {row["name"] for row in payload}
    for expected in ("Demo Cash & CDs", "Demo Retirement", "Demo Brokerage"):
        assert expected in names
    for row in payload:
        assert "position_count" in row
        assert "total_cost" in row


def test_get_portfolio_demo(client: TestClient) -> None:
    r = client.get("/portfolios/Demo%20Brokerage", headers=DEMO_HEADERS)
    assert r.status_code == 200
    payload = r.json()
    assert payload["name"] == "Demo Brokerage"
    assert payload["positions"], "expected positions"
    first = payload["positions"][0]
    for field in ("ticker", "asset_type", "name", "quantity", "cost_basis_per_share"):
        assert field in first


def test_get_portfolio_missing_returns_404(client: TestClient) -> None:
    r = client.get("/portfolios/does-not-exist-xyz", headers=DEMO_HEADERS)
    assert r.status_code == 404
    assert "detail" in r.json()


def test_default_data_dir_used_when_header_absent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No X-Data-Dir header → server falls back to its configured default."""
    monkeypatch.setenv("INVEST_MONITOR_DATA_DIR", "data_demo")
    r = client.get("/portfolios")
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert "Demo Brokerage" in names

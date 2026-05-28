"""Tests for /scenarios HTTP routes via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_list_stress(client: TestClient) -> None:
    r = client.get("/scenarios/stress", headers=DEMO_HEADERS)
    assert r.status_code == 200
    ids = {row["scenario_id"] for row in r.json()}
    assert "2008 Financial Crisis" in ids


def test_list_mc(client: TestClient) -> None:
    r = client.get("/scenarios/mc", headers=DEMO_HEADERS)
    assert r.status_code == 200
    ids = {row["scenario_id"] for row in r.json()}
    assert "base" in ids


def test_list_regimes(client: TestClient) -> None:
    r = client.get("/scenarios/regimes", headers=DEMO_HEADERS)
    assert r.status_code == 200
    assert r.json()


def test_run_stress_with_preset(client: TestClient) -> None:
    r = client.post(
        "/scenarios/stress/Demo Brokerage",
        json={"scenario_id": "2008 Financial Crisis"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_value"] > 0
    assert body["total_change_pct"] < 0
    assert body["rows"]


def test_run_stress_with_custom_shocks(client: TestClient) -> None:
    r = client.post(
        "/scenarios/stress/Demo Brokerage",
        json={"custom_sector_shocks": {"technology": -0.5, "healthcare": -0.5}},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["total_change_pct"] < 0


def test_run_stress_unknown_portfolio_404(client: TestClient) -> None:
    r = client.post(
        "/scenarios/stress/no-such-portfolio",
        json={"scenario_id": "2008 Financial Crisis"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 404


def test_run_stress_unknown_scenario_400(client: TestClient) -> None:
    r = client.post(
        "/scenarios/stress/Demo Brokerage",
        json={"scenario_id": "Bogus"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 400


def test_run_stress_no_shocks_400(client: TestClient) -> None:
    r = client.post(
        "/scenarios/stress/Demo Brokerage",
        json={},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 400

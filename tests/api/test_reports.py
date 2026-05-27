"""Tests for /reports/* HTTP routes via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}
PORTFOLIO = "Demo Retirement"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_risk_route_demo(client: TestClient) -> None:
    r = client.get(f"/reports/risk/{PORTFOLIO}", headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["portfolio_name"] == PORTFOLIO
    assert body["annualised_volatility"] > 0
    assert body["tickers"]
    assert body["covariance_matrix"]


def test_exposure_route_demo(client: TestClient) -> None:
    r = client.get(f"/reports/exposure/{PORTFOLIO}", headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["total_value"] > 0
    assert sum(row["weight_pct"] for row in body["rows"]) == pytest.approx(100.0, abs=0.01)


def test_income_route_demo(client: TestClient) -> None:
    r = client.get(f"/reports/income/{PORTFOLIO}", headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["total_annual_income"] == pytest.approx(
        sum(row["annual_income"] for row in body["rows"])
    )


def test_correlation_route_demo(client: TestClient) -> None:
    r = client.get(f"/reports/correlation/{PORTFOLIO}", headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["tickers"]
    # Diagonal == 1.0
    for t in body["tickers"]:
        assert body["matrix"][t][t] == pytest.approx(1.0, rel=1e-6)


def test_attribution_route_demo(client: TestClient) -> None:
    r = client.get(
        f"/reports/attribution/{PORTFOLIO}?start=2025-01-01&end=2025-06-30&top_n=3",
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["portfolio_name"] == PORTFOLIO
    assert len(body["daily_returns"]) == len(body["dates"])
    assert len(body["top_contributors"]) <= 3


def test_missing_portfolio_returns_404(client: TestClient) -> None:
    for kind in ["risk", "exposure", "income", "correlation", "attribution"]:
        r = client.get(f"/reports/{kind}/does-not-exist", headers=DEMO_HEADERS)
        assert r.status_code == 404, f"{kind} should 404"


def test_attribution_top_n_bounds(client: TestClient) -> None:
    r = client.get(f"/reports/attribution/{PORTFOLIO}?top_n=0", headers=DEMO_HEADERS)
    assert r.status_code == 422
    r = client.get(f"/reports/attribution/{PORTFOLIO}?top_n=51", headers=DEMO_HEADERS)
    assert r.status_code == 422

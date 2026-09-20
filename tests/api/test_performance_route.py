"""Tests for GET /performance."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_performance_route_demo(client: TestClient) -> None:
    r = client.get("/performance", headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["series"]
    assert len(body["portfolio_cumulative_return"]) == len(body["dates"])


def test_performance_scopes(client: TestClient) -> None:
    whole = client.get("/performance", headers=DEMO_HEADERS).json()
    scoped = client.get(
        "/performance", params={"portfolio": "Demo Brokerage"}, headers=DEMO_HEADERS
    )
    assert scoped.status_code == 200
    assert len(scoped.json()["series"]) < len(whole["series"])


def test_unknown_portfolio_is_404(client: TestClient) -> None:
    r = client.get(
        "/performance", params={"portfolio": "No Such Account"}, headers=DEMO_HEADERS
    )
    assert r.status_code == 404

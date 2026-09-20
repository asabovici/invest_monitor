"""Tests for the four aggregate screen routes via FastAPI TestClient.

These endpoints back one front-end screen each. The property under test is
the scoping contract they share: ``?portfolio=`` narrows the payload to one
account, its absence spans every account, and an unknown name is a 404
rather than an empty-but-successful response.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}
PORTFOLIO = "Demo Brokerage"
SCREENS = ["/dashboard", "/exposure", "/risk", "/income"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("path", SCREENS)
def test_unscoped_screen_spans_every_account(client: TestClient, path: str) -> None:
    r = client.get(path, headers=DEMO_HEADERS)
    assert r.status_code == 200
    assert r.json()["market_value"] > 0


@pytest.mark.parametrize("path", SCREENS)
def test_scoped_screen_is_smaller_than_the_whole(client: TestClient, path: str) -> None:
    """Guard against the param being accepted and then ignored."""
    whole = client.get(path, headers=DEMO_HEADERS).json()["market_value"]
    scoped = client.get(
        path, params={"portfolio": PORTFOLIO}, headers=DEMO_HEADERS
    )
    assert scoped.status_code == 200
    assert 0 < scoped.json()["market_value"] < whole


@pytest.mark.parametrize("path", SCREENS)
def test_unknown_portfolio_is_404(client: TestClient, path: str) -> None:
    r = client.get(path, params={"portfolio": "No Such Account"}, headers=DEMO_HEADERS)
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_dashboard_scoped_holdings_carry_one_account(client: TestClient) -> None:
    r = client.get("/dashboard", params={"portfolio": PORTFOLIO}, headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["holdings"]
    assert {h["account"] for h in body["holdings"]} == {PORTFOLIO}
    assert list(body["totals_by_account"]) == [PORTFOLIO]


def test_risk_scoping_composes_with_its_other_params(client: TestClient) -> None:
    """Scope must not displace the projection knobs on the same request."""
    r = client.get(
        "/risk",
        params={
            "portfolio": PORTFOLIO,
            "years": 7,
            "num_simulations": 200,
            "monthly_contribution": 250,
        },
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["projection"]["years"] == 7
    assert body["projection"]["num_simulations"] == 200
    assert body["projection"]["monthly_contribution"] == 250

"""Contract tests for GET /reports/attribution/{portfolio}.

The Attribution screen reads these fields directly; a shape change here
breaks the view silently, so the shape is pinned. These characterise
behaviour that already exists rather than driving new code.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}
PORTFOLIO = "Demo Brokerage"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_attribution_shape(client: TestClient) -> None:
    r = client.get(
        f"/reports/attribution/{PORTFOLIO}", params={"top_n": 5}, headers=DEMO_HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["daily_returns"]) == len(body["dates"])
    assert len(body["top_contributors"]) <= 5
    for row in body["top_contributors"]:
        assert {"ticker", "contribution_to_return"} <= row.keys()


def test_attribution_window_is_reported(client: TestClient) -> None:
    """The view states the window, because it differs per portfolio."""
    body = client.get(
        f"/reports/attribution/{PORTFOLIO}", headers=DEMO_HEADERS
    ).json()
    assert body["start_date"] <= body["end_date"]
    assert body["portfolio_name"] == PORTFOLIO


def test_unknown_portfolio_is_404(client: TestClient) -> None:
    r = client.get("/reports/attribution/No Such Account", headers=DEMO_HEADERS)
    assert r.status_code == 404

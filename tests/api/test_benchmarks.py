"""Tests for /benchmarks HTTP routes via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_list_benchmarks(client: TestClient) -> None:
    r = client.get("/benchmarks", headers=DEMO_HEADERS)
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert "60/40 Classic" in names


def test_benchmark_stats_known(client: TestClient) -> None:
    # URL-encode the slash in '60/40 Classic'.
    r = client.get("/benchmarks/60%2F40 Classic/stats", headers=DEMO_HEADERS)
    assert r.status_code == 200
    assert r.json()["name"] == "60/40 Classic"


def test_benchmark_stats_unknown_404(client: TestClient) -> None:
    r = client.get("/benchmarks/Imaginary/stats", headers=DEMO_HEADERS)
    assert r.status_code == 404


def test_benchmark_returns_known(client: TestClient) -> None:
    r = client.get("/benchmarks/Golden Butterfly/returns", headers=DEMO_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Golden Butterfly"
    assert len(body["cumulative_returns"]) == len(body["dates"])


def test_compare_to_benchmark(client: TestClient) -> None:
    r = client.get(
        "/benchmarks/60%2F40 Classic/compare/Demo Retirement",
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["portfolio_name"] == "Demo Retirement"
    assert body["benchmark_name"] == "60/40 Classic"
    assert len(body["portfolio_cumulative_returns"]) == len(body["dates"])
    assert len(body["benchmark_cumulative_returns"]) == len(body["dates"])


def test_compare_unknown_portfolio_404(client: TestClient) -> None:
    r = client.get(
        "/benchmarks/60%2F40 Classic/compare/no-such-portfolio",
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 404


def test_compare_unknown_benchmark_404(client: TestClient) -> None:
    r = client.get(
        "/benchmarks/Imaginary/compare/Demo Retirement",
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 404

"""Tests for /trading-graph routes via FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.services import trading_graph as graph_service


@pytest.fixture(autouse=True)
def fresh_caches():
    graph_service.reset_runs()
    yield
    graph_service.reset_runs()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_start_no_hitl_completes(client: TestClient) -> None:
    r = client.post(
        "/trading-graph/runs",
        json={"settings": {"human_in_the_loop": False}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["is_complete"]
    assert body["final_execution_ready"]


def test_start_hitl_pauses(client: TestClient) -> None:
    r = client.post("/trading-graph/runs", json={})
    assert r.status_code == 201
    body = r.json()
    assert body["is_paused_for_hitl"]
    assert body["next_nodes"] == ["cio"]


def test_start_with_no_body(client: TestClient) -> None:
    """Empty body falls back to defaults (HITL on)."""
    r = client.post("/trading-graph/runs")
    assert r.status_code == 201
    assert r.json()["is_paused_for_hitl"]


def test_get_run(client: TestClient) -> None:
    run_id = client.post("/trading-graph/runs", json={}).json()["run_id"]
    r = client.get(f"/trading-graph/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["next_nodes"] == ["cio"]


def test_resume_completes(client: TestClient) -> None:
    run_id = client.post("/trading-graph/runs", json={}).json()["run_id"]
    r = client.post(f"/trading-graph/runs/{run_id}/resume", json={})
    assert r.status_code == 200
    assert r.json()["is_complete"]


def test_resume_with_state_patch(client: TestClient) -> None:
    run_id = client.post("/trading-graph/runs", json={}).json()["run_id"]
    override = {"allocation": {"OVRD": 1.0}, "revision": 7}
    r = client.post(
        f"/trading-graph/runs/{run_id}/resume",
        json={"state_patch": {"proposed_trades": override}},
    )
    assert r.status_code == 200
    assert r.json()["proposed_trades"] == override


def test_get_unknown_run_404(client: TestClient) -> None:
    assert client.get("/trading-graph/runs/no-such").status_code == 404


def test_resume_unknown_run_404(client: TestClient) -> None:
    r = client.post("/trading-graph/runs/no-such/resume", json={})
    assert r.status_code == 404


def test_end_run_204(client: TestClient) -> None:
    run_id = client.post("/trading-graph/runs", json={}).json()["run_id"]
    r = client.delete(f"/trading-graph/runs/{run_id}")
    assert r.status_code == 204
    assert client.get(f"/trading-graph/runs/{run_id}").status_code == 404


def test_settings_validation_caps_max_revisions(client: TestClient) -> None:
    """Pydantic ge/le on max_revisions rejects out-of-range values."""
    r = client.post(
        "/trading-graph/runs",
        json={"settings": {"max_revisions": 0}},
    )
    assert r.status_code == 422

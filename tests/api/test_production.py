"""Tests for /production routes via FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.services import production as production_service


def _ok_job(db):
    return {"status": "ok"}


def _failing_job(db):
    raise RuntimeError("boom")


_STUB_REGISTRY = {
    "stub_ok": {
        "callable":         _ok_job,
        "interval_minutes": 60,
        "description":      "Stubbed success.",
    },
    "stub_fail": {
        "callable":         _failing_job,
        "interval_minutes": 60,
        "description":      "Stubbed failure.",
    },
}


@pytest.fixture(autouse=True)
def stub_registry(monkeypatch):
    import src.production as prod_mod
    monkeypatch.setattr(prod_mod, "JOB_REGISTRY", _STUB_REGISTRY)
    monkeypatch.setattr(production_service, "JOB_REGISTRY", _STUB_REGISTRY)
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def headers(tmp_path) -> dict[str, str]:
    return {"X-Data-Dir": str(tmp_path)}


def test_list_jobs(client: TestClient, headers) -> None:
    r = client.get("/production/jobs", headers=headers)
    assert r.status_code == 200
    assert {j["job_name"] for j in r.json()} == {"stub_ok", "stub_fail"}


def test_get_job_unknown_404(client: TestClient, headers) -> None:
    assert client.get("/production/jobs/no-such", headers=headers).status_code == 404


def test_run_job_success(client: TestClient, headers) -> None:
    r = client.post("/production/jobs/stub_ok/run", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert r.json()["details"] == {"status": "ok"}


def test_run_job_failure_captures_error(client: TestClient, headers) -> None:
    r = client.post("/production/jobs/stub_fail/run", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "boom" in (body["error"] or "")


def test_run_job_unknown_404(client: TestClient, headers) -> None:
    r = client.post("/production/jobs/no-such/run", headers=headers)
    assert r.status_code == 404


def test_set_job_enabled(client: TestClient, headers) -> None:
    # Seed jobs first.
    client.get("/production/jobs", headers=headers)
    r = client.patch("/production/jobs/stub_ok?enabled=false", headers=headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_run_due(client: TestClient, headers) -> None:
    # Seed (all jobs due since never_run).
    client.get("/production/jobs", headers=headers)
    r = client.post("/production/run-due", headers=headers)
    assert r.status_code == 200
    assert {x["job_name"] for x in r.json()["results"]} == {"stub_ok", "stub_fail"}


def test_list_runs(client: TestClient, headers) -> None:
    client.post("/production/jobs/stub_ok/run", headers=headers)
    r = client.get("/production/runs?limit=10", headers=headers)
    assert r.status_code == 200
    assert any(rec["job_name"] == "stub_ok" for rec in r.json())


def test_list_runs_limit_validation(client: TestClient, headers) -> None:
    assert client.get("/production/runs?limit=0", headers=headers).status_code == 422
    assert client.get("/production/runs?limit=600", headers=headers).status_code == 422

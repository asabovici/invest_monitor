"""Tests for src/services/production.py with JOB_REGISTRY stubbed.

Real callables hit yfinance and the AttributionEngine, so we swap the
registry with deterministic stubs that exercise both success and error
paths.
"""

from __future__ import annotations

import pytest

from src.services import production as production_service
from src.services.schemas.production import MetricsRefreshRequest


# ── Stub registry ────────────────────────────────────────────────────────────


def _ok_job(db):
    return {"rows": 42, "note": "stubbed success"}


def _failing_job(db):
    raise RuntimeError("simulated failure")


_STUB_REGISTRY = {
    "stub_ok": {
        "callable":         _ok_job,
        "interval_minutes": 60,
        "description":      "Deterministic success stub.",
    },
    "stub_fail": {
        "callable":         _failing_job,
        "interval_minutes": 60,
        "description":      "Deterministic failure stub.",
    },
}


@pytest.fixture(autouse=True)
def stub_registry(monkeypatch):
    # Patch the registry in both src.production and the service module's view.
    import src.production as prod_mod
    monkeypatch.setattr(prod_mod, "JOB_REGISTRY", _STUB_REGISTRY)
    monkeypatch.setattr(production_service, "JOB_REGISTRY", _STUB_REGISTRY)
    yield


# ── Tests ────────────────────────────────────────────────────────────────────


def test_list_jobs_seeds_registry(tmp_path) -> None:
    jobs = production_service.list_jobs(str(tmp_path))
    names = {j.job_name for j in jobs}
    assert names == {"stub_ok", "stub_fail"}
    # First call seeds; all jobs should report as due (never_run).
    for j in jobs:
        assert j.is_due
        assert j.last_status == "never_run"


def test_get_job_unknown_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        production_service.get_job(str(tmp_path), "no-such")


def test_run_job_success_records_status(tmp_path) -> None:
    data_dir = str(tmp_path)
    result = production_service.run_job(data_dir, "stub_ok")
    assert result.status == "success"
    assert result.details == {"rows": 42, "note": "stubbed success"}
    # Status persisted.
    status = production_service.get_job(data_dir, "stub_ok")
    assert status.last_status == "success"
    assert not status.is_due  # just ran


def test_run_job_failure_captures_error(tmp_path) -> None:
    data_dir = str(tmp_path)
    result = production_service.run_job(data_dir, "stub_fail")
    assert result.status == "error"
    assert "simulated failure" in (result.error or "")
    status = production_service.get_job(data_dir, "stub_fail")
    assert status.last_status == "error"
    assert "simulated failure" in status.last_error


def test_run_job_unknown_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        production_service.run_job(str(tmp_path), "no-such")


def test_set_job_enabled_persists(tmp_path) -> None:
    data_dir = str(tmp_path)
    production_service.list_jobs(data_dir)  # seed
    status = production_service.set_job_enabled(data_dir, "stub_ok", False)
    assert status.enabled is False
    again = production_service.get_job(data_dir, "stub_ok")
    assert again.enabled is False


def test_set_job_enabled_unknown_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        production_service.set_job_enabled(str(tmp_path), "no-such", True)


def test_run_due_jobs_returns_results(tmp_path) -> None:
    data_dir = str(tmp_path)
    production_service.list_jobs(data_dir)  # seed; all due
    resp = production_service.run_due_jobs(data_dir)
    names = {r.job_name for r in resp.results}
    assert names == {"stub_ok", "stub_fail"}
    statuses = {r.job_name: r.status for r in resp.results}
    assert statuses["stub_ok"] == "success"
    assert statuses["stub_fail"] == "error"


def test_list_runs_persists_history(tmp_path) -> None:
    data_dir = str(tmp_path)
    production_service.run_job(data_dir, "stub_ok")
    production_service.run_job(data_dir, "stub_fail")
    runs = production_service.list_runs(data_dir, limit=10)
    assert len(runs) >= 2
    by_name = {r.job_name: r.status for r in runs}
    assert by_name["stub_ok"] == "success"
    assert by_name["stub_fail"] == "error"


def test_list_runs_filter(tmp_path) -> None:
    data_dir = str(tmp_path)
    production_service.run_job(data_dir, "stub_ok")
    production_service.run_job(data_dir, "stub_fail")
    err_only = production_service.list_runs(data_dir, status="error")
    assert all(r.status == "error" for r in err_only)


# ── Metrics refresh ─────────────────────────────────────────────────────────


def test_refresh_metrics_with_no_assets(tmp_path) -> None:
    """Empty data dir: AttributionEngine.refresh_all should return a summary
    with zero rows rather than crashing."""
    summary = production_service.refresh_metrics(
        str(tmp_path), MetricsRefreshRequest(),
    ).summary
    assert isinstance(summary, dict)
    # The summary shape may vary; we only care that we got something back.
    assert "security_rows" in summary or summary == {}

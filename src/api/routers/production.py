"""HTTP routes for the production-job runner (slice 9).

Two of these endpoints are **long-running and synchronous** — both
``POST /production/jobs/{name}/run`` (especially ``collect_prices``,
which hits yfinance per ticker) and ``POST /production/metrics-refresh``
can hold a worker for minutes on a large portfolio. Document this in the
client and prefer the CLI / systemd timer path for production workloads.

Systemd-timer management (``invest-monitor production schedule install``
etc.) intentionally stays admin-only — installing host services over
HTTP is out of scope.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.api.deps import data_dir_dep
from src.services import production as production_service
from src.services.schemas.production import (
    JobStatus,
    MetricsRefreshRequest,
    MetricsRefreshResult,
    RunDueResponse,
    RunRecord,
    RunResult,
)

router = APIRouter(prefix="/production", tags=["production"])


# ── Jobs ─────────────────────────────────────────────────────────────────────


@router.get("/jobs", response_model=list[JobStatus])
def list_jobs(
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> list[JobStatus]:
    """Every registered job with its persisted status + due flag."""
    return production_service.list_jobs(data_dir)


@router.get("/jobs/{job_name}", response_model=JobStatus)
def get_job(
    job_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> JobStatus:
    """One job's status. 404 if unknown."""
    return production_service.get_job(data_dir, job_name)


@router.patch("/jobs/{job_name}", response_model=JobStatus)
def set_job_enabled(
    job_name: str,
    enabled: Annotated[bool, Query(description="True to enable, False to disable.")],
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> JobStatus:
    """Flip the job's ``enabled`` flag. 404 if unknown."""
    return production_service.set_job_enabled(data_dir, job_name, enabled)


@router.post("/jobs/{job_name}/run", response_model=RunResult)
def run_job(
    job_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
    force: Annotated[
        bool,
        Query(description="Run even if the job is disabled."),
    ] = False,
) -> RunResult:
    """Manually run one job. **Synchronous and long-running.** 404 if unknown."""
    return production_service.run_job(data_dir, job_name, force=force)


@router.post("/run-due", response_model=RunDueResponse)
def run_due(
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> RunDueResponse:
    """Run every job whose interval has elapsed. Cron-friendly one-shot."""
    return production_service.run_due_jobs(data_dir)


# ── Run log ──────────────────────────────────────────────────────────────────


@router.get("/runs", response_model=list[RunRecord])
def list_runs(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    job_name: Annotated[str | None, Query()] = None,
    run_status: Annotated[
        str | None,
        Query(alias="status", description="Filter to success / error / skipped."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[RunRecord]:
    """Newest-first slice of the production-runs log."""
    return production_service.list_runs(
        data_dir, job_name=job_name, status=run_status, limit=limit,
    )


# ── Metrics refresh ──────────────────────────────────────────────────────────


@router.post(
    "/metrics-refresh",
    response_model=MetricsRefreshResult,
    status_code=status.HTTP_200_OK,
)
def metrics_refresh(
    body: MetricsRefreshRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> MetricsRefreshResult:
    """Recompute daily security / portfolio / attribution metrics.

    **Synchronous and long-running.** Pass ``full=true`` to ignore the
    incremental anchor and recompute the full history (e.g. after a
    trade backfill).
    """
    return production_service.refresh_metrics(data_dir, body)

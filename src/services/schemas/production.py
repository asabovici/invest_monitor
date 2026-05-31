"""Pydantic schemas for production-job endpoints (slice 9)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# Status of a finished ``run_job`` call. Constrained because the job
# runner only ever writes these three values.
RunStatus = Literal["success", "error", "skipped"]


class JobStatus(BaseModel):
    """One row in the production-jobs catalogue.

    ``last_status`` is a free-form string rather than a ``Literal`` so
    the API doesn't reject a parquet row written by an older / newer
    job runner that knows about additional statuses. Today the runner
    writes ``"never_run"``, ``"success"``, ``"error"``, or ``"running"``.
    """

    job_name: str
    description: str = ""
    enabled: bool
    interval_minutes: int
    last_run_at: datetime | None = None
    last_status: str = "never_run"
    last_error: str = ""
    last_duration_seconds: float | None = None
    is_due: bool


class RunResult(BaseModel):
    """Outcome of a single ``run_job`` call."""

    job_name: str
    status: RunStatus
    duration_seconds: float = 0.0
    details: dict[str, Any] | None = None
    error: str | None = None


class RunRecord(BaseModel):
    """One row from the production-runs log (newest-first)."""

    job_name: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str
    duration_seconds: float | None = None
    error_message: str = ""
    details: str = ""


class RunDueResponse(BaseModel):
    """``POST /production/run-due`` returns the result of every triggered job."""

    results: list[RunResult]


class MetricsRefreshRequest(BaseModel):
    """Body for ``POST /production/metrics-refresh``."""

    portfolio_name: str | None = Field(
        None,
        description="Refresh only this portfolio (default: all).",
    )
    start_date: str | None = Field(
        None,
        description="ISO date; recompute from this date forward (incremental).",
    )
    full: bool = Field(
        False,
        description="Ignore incremental anchors and recompute the full history.",
    )


class MetricsRefreshResult(BaseModel):
    """Summary returned by ``AttributionEngine.refresh_all``."""

    summary: dict[str, Any]

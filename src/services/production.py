"""Production / job-runner service: status, manual run, run-due, run log.

Slice 9 of the API refactor — see API_REFACTOR_PLAN.md §5. Wraps
``src.production.JobRunner`` and ``src.attribution.AttributionEngine``
behind typed functions. Scheduler / systemd-timer concerns stay
admin-only (CLI), since installing host services over HTTP is out of
scope for this codebase.
"""

from __future__ import annotations

import pandas as pd

from src.attribution import AttributionEngine
from src.production import JOB_REGISTRY, JobRunner
from src.services._db import _get_db
from src.services.schemas.production import (
    JobStatus,
    MetricsRefreshRequest,
    MetricsRefreshResult,
    RunDueResponse,
    RunRecord,
    RunResult,
)


# ── Jobs ─────────────────────────────────────────────────────────────────────


def _row_to_status(runner: JobRunner, row: pd.Series, now: pd.Timestamp) -> JobStatus:
    name = row["job_name"]
    cfg = JOB_REGISTRY.get(name, {})
    last_run = row.get("last_run_at")
    return JobStatus(
        job_name=name,
        description=str(cfg.get("description", "")),
        enabled=bool(row["enabled"]),
        interval_minutes=int(row["interval_minutes"]),
        last_run_at=None if pd.isna(last_run) else pd.Timestamp(last_run).to_pydatetime(),
        last_status=str(row.get("last_status") or "never_run"),
        last_error=str(row.get("last_error") or ""),
        last_duration_seconds=(
            None
            if pd.isna(row.get("last_duration_seconds"))
            else float(row["last_duration_seconds"])
        ),
        is_due=runner.is_due(row, now=now),
    )


def list_jobs(data_dir: str) -> list[JobStatus]:
    """Return every registered job with its persisted status."""
    db = _get_db(data_dir)
    runner = JobRunner(db)
    jobs = db.get_production_jobs().sort_values("job_name")
    now = pd.Timestamp.now()
    return [_row_to_status(runner, r, now) for _, r in jobs.iterrows()]


def get_job(data_dir: str, job_name: str) -> JobStatus:
    """One job's persisted status. Raises ``ValueError`` if unknown."""
    if job_name not in JOB_REGISTRY:
        raise ValueError(f"Job {job_name!r} not found.")
    db = _get_db(data_dir)
    runner = JobRunner(db)
    jobs = db.get_production_jobs()
    matches = jobs[jobs["job_name"] == job_name] if not jobs.empty else pd.DataFrame()
    if matches.empty:
        # Registered but never seeded yet — return a clean placeholder.
        cfg = JOB_REGISTRY[job_name]
        return JobStatus(
            job_name=job_name,
            description=str(cfg.get("description", "")),
            enabled=True,
            interval_minutes=int(cfg["interval_minutes"]),
            last_run_at=None,
            last_status="never_run",
            last_error="",
            last_duration_seconds=None,
            is_due=True,
        )
    return _row_to_status(runner, matches.iloc[0], pd.Timestamp.now())


def run_job(data_dir: str, job_name: str, force: bool = False) -> RunResult:
    """Manually trigger one job. ``force=True`` overrides the disabled flag.

    Synchronous and potentially long-running — the underlying callables
    can hit yfinance for many tickers. Raises ``ValueError`` if the job
    is unknown.
    """
    if job_name not in JOB_REGISTRY:
        raise ValueError(f"Job {job_name!r} not found.")
    runner = JobRunner(_get_db(data_dir))
    raw = runner.run_job(job_name, force=force)
    return RunResult(
        job_name=raw.get("job_name", job_name),
        status=raw.get("status", "error"),
        duration_seconds=float(raw.get("duration_seconds") or 0.0),
        details=raw.get("details") if isinstance(raw.get("details"), dict) else None,
        error=raw.get("error"),
    )


def set_job_enabled(data_dir: str, job_name: str, enabled: bool) -> JobStatus:
    """Flip a job's ``enabled`` flag. Raises ``ValueError`` if unknown.

    Instantiating ``JobRunner`` first runs the idempotent
    ``_ensure_jobs_seeded`` step, so the row that ``upsert_production_job``
    targets already carries the ``interval_minutes`` / ``last_status``
    defaults from ``JOB_REGISTRY`` rather than NaN.
    """
    if job_name not in JOB_REGISTRY:
        raise ValueError(f"Job {job_name!r} not found.")
    db = _get_db(data_dir)
    JobRunner(db)  # idempotent seed
    db.upsert_production_job(job_name, enabled=enabled)
    return get_job(data_dir, job_name)


def run_due_jobs(data_dir: str) -> RunDueResponse:
    """Run every job whose ``last_run_at + interval_minutes`` has elapsed.

    Cron-friendly: returns an empty list when nothing's due.
    """
    runner = JobRunner(_get_db(data_dir))
    raw_results = runner.run_due_jobs()
    return RunDueResponse(results=[
        RunResult(
            job_name=r.get("job_name", ""),
            status=r.get("status", "error"),
            duration_seconds=float(r.get("duration_seconds") or 0.0),
            details=r.get("details") if isinstance(r.get("details"), dict) else None,
            error=r.get("error"),
        )
        for r in raw_results
    ])


# ── Run log ──────────────────────────────────────────────────────────────────


def list_runs(
    data_dir: str,
    job_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[RunRecord]:
    """Recent rows from ``production_runs.parquet``, newest-first."""
    df = _get_db(data_dir).get_production_runs(
        job_name=job_name, status=status, limit=limit,
    )
    if df.empty:
        return []
    return [
        RunRecord(
            job_name=str(r["job_name"]),
            started_at=(
                None if pd.isna(r.get("started_at")) else pd.Timestamp(r["started_at"]).to_pydatetime()
            ),
            ended_at=(
                None if pd.isna(r.get("ended_at")) else pd.Timestamp(r["ended_at"]).to_pydatetime()
            ),
            status=str(r["status"]),
            duration_seconds=(
                None if pd.isna(r.get("duration_seconds")) else float(r["duration_seconds"])
            ),
            error_message=str(r.get("error_message") or ""),
            details=str(r.get("details") or ""),
        )
        for _, r in df.iterrows()
    ]


# ── Metrics refresh ──────────────────────────────────────────────────────────


def refresh_metrics(data_dir: str, body: MetricsRefreshRequest) -> MetricsRefreshResult:
    """Run ``AttributionEngine.refresh_all`` with the requested scope.

    Like the price-collect endpoint, this is synchronous and can take
    minutes on a large portfolio — call from a background context or via
    the CLI when wiring into cron.
    """
    engine = AttributionEngine(_get_db(data_dir))
    summary = engine.refresh_all(
        start_date=body.start_date,
        portfolio_name=body.portfolio_name,
        full=body.full,
    )
    return MetricsRefreshResult(summary=summary or {})


__all__ = [
    "list_jobs",
    "get_job",
    "set_job_enabled",
    "run_job",
    "run_due_jobs",
    "list_runs",
    "refresh_metrics",
]

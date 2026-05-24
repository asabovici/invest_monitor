"""Analytics & return production runner.

Scheduled-job machinery for the periodic data refreshes the dashboard depends
on: pulling prices, recomputing daily attribution, refreshing sector betas and
fund profiles. Each job's last run + any error is persisted to parquet so the
Streamlit Production view can surface issues.

Wiring options:
  * One-shot:  `invest-monitor production run`   (runs only what's due, cron-friendly)
  * Daemon :   `invest-monitor production daemon`  (long-running loop with sleep)
  * Manual:    the Production view in the dashboard has a `Run all due` button
              plus per-job `Run now` controls.
"""
from __future__ import annotations

import json
import time
import traceback
from typing import Any, Callable, Optional

import pandas as pd

from src.attribution import AttributionEngine
from src.collector import Collector
from src.database import Database


# ── Built-in jobs ─────────────────────────────────────────────────────────────

def _collect_prices_job(db: Database) -> dict:
    Collector(db).update_all_assets(period="1mo")
    return {"action": "Pulled trailing-month prices for every asset in the master."}


def _refresh_attribution_job(db: Database) -> dict:
    return AttributionEngine(db).refresh_all()


def _refresh_sector_betas_job(db: Database) -> dict:
    betas = Collector.fetch_sector_betas(years=20)
    db.save_sector_betas(betas)
    return {"betas_rows": len(betas), "as_of": pd.Timestamp.today().date().isoformat()}


def _refresh_fund_profiles_job(db: Database) -> dict:
    assets = db.get_all_assets()
    if assets.empty:
        return {"refreshed": [], "failed": [], "note": "No assets in the master."}
    fund_tickers = assets.loc[assets["asset_type"].isin(["ETF", "Fund"]), "ticker"].tolist()
    today = pd.Timestamp.today().date().isoformat()
    refreshed: list[str] = []
    failed: list[str] = []
    for t in fund_tickers:
        try:
            prof = Collector(db).fetch_fund_profile(t)
            db.save_fund_profile(t, today, prof["asset_classes"], prof["sector_weightings"])
            refreshed.append(t)
        except Exception as exc:
            failed.append(f"{t}: {exc}")
    return {"refreshed": refreshed, "failed": failed}


JobCallable = Callable[[Database], dict]


JOB_REGISTRY: dict[str, dict[str, Any]] = {
    "collect_prices": {
        "callable":         _collect_prices_job,
        "interval_minutes": 60 * 24,           # daily
        "description":      "Fetch latest yfinance prices for every tracked ticker.",
    },
    "refresh_attribution": {
        "callable":         _refresh_attribution_job,
        "interval_minutes": 60 * 24,           # daily
        "description":      "Recompute daily security / portfolio / attribution metrics.",
    },
    "refresh_sector_betas": {
        "callable":         _refresh_sector_betas_job,
        "interval_minutes": 60 * 24 * 7,       # weekly
        "description":      "Rebuild the 20-year SPDR sector-ETF beta matrix.",
    },
    "refresh_fund_profiles": {
        "callable":         _refresh_fund_profiles_job,
        "interval_minutes": 60 * 24 * 7,       # weekly
        "description":      "Fetch yfinance asset_classes + sector_weightings for held ETFs/Funds.",
    },
}


# ── Runner ────────────────────────────────────────────────────────────────────

class JobRunner:
    """Wraps the registered jobs with persistence + error capture."""

    def __init__(self, db: Database):
        self.db = db
        self._ensure_jobs_seeded()

    def _ensure_jobs_seeded(self) -> None:
        existing = self.db.get_production_jobs()
        existing_names = set(existing["job_name"].tolist()) if not existing.empty else set()
        for name, cfg in JOB_REGISTRY.items():
            if name not in existing_names:
                self.db.upsert_production_job(
                    name,
                    enabled=True,
                    interval_minutes=cfg["interval_minutes"],
                    last_status="never_run",
                )

    # ── Single job ────────────────────────────────────────────────────────────

    def run_job(self, name: str, force: bool = False) -> dict:
        """Execute one job. Captures exceptions, persists status + run log."""
        if name not in JOB_REGISTRY:
            raise ValueError(f"Unknown job: {name}")

        jobs = self.db.get_production_jobs()
        job_row = (
            jobs[jobs["job_name"] == name].iloc[0]
            if not jobs.empty and (jobs["job_name"] == name).any()
            else None
        )
        if (not force) and (job_row is not None) and (not bool(job_row["enabled"])):
            return {"job_name": name, "status": "skipped", "reason": "disabled"}

        cfg = JOB_REGISTRY[name]
        started = pd.Timestamp.now()
        try:
            result = cfg["callable"](self.db) or {}
            ended = pd.Timestamp.now()
            duration = (ended - started).total_seconds()
            details = json.dumps(result, default=str)
            self.db.append_production_run(
                job_name=name, started_at=started, ended_at=ended,
                status="success", details=details, duration_seconds=duration,
            )
            self.db.upsert_production_job(
                name,
                last_run_at=started,
                last_status="success",
                last_error="",       # clear any previous error
                last_duration_seconds=duration,
            )
            return {"job_name": name, "status": "success",
                    "duration_seconds": duration, "details": result}
        except Exception as exc:
            ended = pd.Timestamp.now()
            duration = (ended - started).total_seconds()
            err_text = f"{exc.__class__.__name__}: {exc}"
            tb = traceback.format_exc(limit=4)
            self.db.append_production_run(
                job_name=name, started_at=started, ended_at=ended,
                status="error", error_message=err_text,
                details=tb, duration_seconds=duration,
            )
            self.db.upsert_production_job(
                name,
                last_run_at=started,
                last_status="error",
                last_error=err_text,
                last_duration_seconds=duration,
            )
            return {"job_name": name, "status": "error",
                    "error": err_text, "duration_seconds": duration}

    # ── Due / all ─────────────────────────────────────────────────────────────

    def is_due(self, row: pd.Series, now: Optional[pd.Timestamp] = None) -> bool:
        if not bool(row["enabled"]):
            return False
        now = now or pd.Timestamp.now()
        if pd.isna(row["last_run_at"]):
            return True
        elapsed_min = (now - row["last_run_at"]).total_seconds() / 60.0
        return elapsed_min >= float(row["interval_minutes"])

    def run_due_jobs(self) -> list[dict]:
        results: list[dict] = []
        now = pd.Timestamp.now()
        jobs = self.db.get_production_jobs()
        if jobs.empty:
            return results
        for _, row in jobs.iterrows():
            if self.is_due(row, now=now):
                results.append(self.run_job(row["job_name"]))
        return results

    def daemon(self, check_every_seconds: int = 60, *, stop_after: Optional[int] = None) -> None:
        """Long-running loop. `stop_after` (seconds) is used in tests."""
        deadline = (time.time() + stop_after) if stop_after else None
        while True:
            self.run_due_jobs()
            if deadline is not None and time.time() >= deadline:
                return
            time.sleep(check_every_seconds)

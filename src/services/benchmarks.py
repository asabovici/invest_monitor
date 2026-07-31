"""Benchmarks service: catalogue, returns series, portfolio comparison.

Slice 5 of the API refactor — see API_REFACTOR_PLAN.md §5.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable

import numpy as np
import pandas as pd

from src.services.schemas.benchmark import (
    BenchmarkComparison,
    BenchmarkInfo,
    BenchmarkReturnsSeries,
    BenchmarkStats,
)
from src.benchmarks import (
    BENCHMARKS,
    benchmark_daily_returns as _bench_daily,
    benchmark_stats as _bench_stats,
)
from src.services._db import _get_db


# ── Catalogue ────────────────────────────────────────────────────────────────


def list_benchmarks() -> list[BenchmarkInfo]:
    """Return the static catalogue of named benchmark portfolios."""
    return [
        BenchmarkInfo(name=b.name, description=b.description, weights=dict(b.weights))
        for b in BENCHMARKS.values()
    ]


# ── Returns series + stats ───────────────────────────────────────────────────


def _resolve_benchmark(benchmark_name: str):
    if benchmark_name not in BENCHMARKS:
        raise ValueError(f"Benchmark {benchmark_name!r} not found.")
    return BENCHMARKS[benchmark_name]


def _series_to_lists(series: pd.Series) -> tuple[list[date], list[float]]:
    if series.empty:
        return [], []
    dates = [pd.Timestamp(d).date() for d in series.index]
    values = [float(v) for v in series.values]
    return dates, values


def benchmark_returns(
    data_dir: str,
    benchmark_name: str,
    start: date | str | None = None,
) -> BenchmarkReturnsSeries:
    """Daily + cumulative returns for a benchmark, optionally from ``start``."""
    bench = _resolve_benchmark(benchmark_name)
    db = _get_db(data_dir)
    start_str = start.isoformat() if isinstance(start, date) else start
    daily = _bench_daily(bench, db, start_date=start_str)
    cum = (1.0 + daily).cumprod() - 1.0 if not daily.empty else daily

    dates_d, daily_vals = _series_to_lists(daily)
    _, cum_vals = _series_to_lists(cum)
    return BenchmarkReturnsSeries(
        name=bench.name,
        dates=dates_d,
        daily_returns=daily_vals,
        cumulative_returns=cum_vals,
    )


def benchmark_stats(
    data_dir: str,
    benchmark_name: str,
    start: date | str | None = None,
) -> BenchmarkStats:
    """Period return, annualised vol, max drawdown for the named benchmark."""
    bench = _resolve_benchmark(benchmark_name)
    db = _get_db(data_dir)
    start_str = start.isoformat() if isinstance(start, date) else start
    stats = _bench_stats(bench, db, start_date=start_str)
    return BenchmarkStats(
        name=bench.name,
        period_return=stats.get("period_return"),
        vol_annualised=stats.get("vol_annualised"),
        max_drawdown=stats.get("max_drawdown"),
    )


# ── Portfolio comparison ─────────────────────────────────────────────────────


def compare_to_benchmark(
    data_dir: str,
    portfolio_name: str,
    benchmark_name: str,
    start: date | str | None = None,
) -> BenchmarkComparison:
    """Overlay a portfolio's persisted daily-return series against a benchmark.

    Uses ``daily_portfolio_metrics`` for the portfolio side, so run
    ``invest-monitor metrics refresh`` first if values look empty. Aligns
    the two on the intersection of available dates; non-aligned dates
    produce ``None`` in the per-leg arrays.

    Raises:
        ValueError: benchmark unknown, or portfolio not found.
    """
    bench = _resolve_benchmark(benchmark_name)
    db = _get_db(data_dir)
    # Verify the portfolio exists in the portfolios table even if its daily
    # metrics haven't been refreshed yet.
    if portfolio_name not in db.list_portfolios():
        raise ValueError(f"Portfolio '{portfolio_name}' not found.")

    start_str = start.isoformat() if isinstance(start, date) else start
    portfolio_df = db.get_daily_portfolio_metrics(
        portfolio_name=portfolio_name, start_date=start_str,
    )
    bench_daily = _bench_daily(bench, db, start_date=start_str)

    # Build a single date index across both legs (union — None where missing).
    pf_cum = (
        portfolio_df.assign(date=pd.to_datetime(portfolio_df["date"]))
        .set_index("date")["cum_return"]
        if not portfolio_df.empty
        else pd.Series(dtype=float)
    )
    bench_cum = (1.0 + bench_daily).cumprod() - 1.0 if not bench_daily.empty else bench_daily

    all_dates = sorted(set(pf_cum.index).union(set(bench_cum.index)))
    pf_aligned = pf_cum.reindex(all_dates)
    bench_aligned = bench_cum.reindex(all_dates)

    dates_out = [pd.Timestamp(d).date() for d in all_dates]
    pf_vals: list[float | None] = [
        None if pd.isna(v) else float(v) for v in pf_aligned.values
    ]
    bench_vals: list[float | None] = [
        None if pd.isna(v) else float(v) for v in bench_aligned.values
    ]

    pf_stats = _portfolio_stats(portfolio_df, portfolio_name)
    bench_stats_obj = benchmark_stats(data_dir, benchmark_name, start=start)
    return BenchmarkComparison(
        portfolio_name=portfolio_name,
        benchmark_name=bench.name,
        dates=dates_out,
        portfolio_cumulative_returns=pf_vals,
        benchmark_cumulative_returns=bench_vals,
        portfolio_stats=pf_stats,
        benchmark_stats=bench_stats_obj,
    )


def _portfolio_stats(portfolio_df: pd.DataFrame, portfolio_name: str) -> BenchmarkStats:
    """Re-use the BenchmarkStats schema for the portfolio side of the overlay."""
    if portfolio_df.empty:
        return BenchmarkStats(name=portfolio_name)
    daily = portfolio_df["daily_return"].dropna()
    cum_col = portfolio_df["cum_return"].dropna()
    period_return = float(cum_col.iloc[-1]) if not cum_col.empty else None
    vol = float(daily.std() * np.sqrt(252.0)) if len(daily) >= 2 else None
    max_dd_col = portfolio_df["max_drawdown"].dropna()
    max_dd = float(max_dd_col.min()) if not max_dd_col.empty else None
    return BenchmarkStats(
        name=portfolio_name,
        period_return=period_return,
        vol_annualised=vol,
        max_drawdown=max_dd,
    )


__all__ = [
    "list_benchmarks",
    "benchmark_returns",
    "benchmark_stats",
    "compare_to_benchmark",
]

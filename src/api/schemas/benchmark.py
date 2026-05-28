"""Pydantic schemas for benchmark endpoints (slice 5)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class BenchmarkInfo(BaseModel):
    """One row in the benchmark catalogue."""

    name: str
    description: str
    weights: dict[str, float] = Field(
        ..., description="ETF-proxy ticker → weight (should sum to ~1.0)."
    )


class BenchmarkReturnsSeries(BaseModel):
    """Daily and cumulative return series for a benchmark."""

    name: str
    dates: list[date]
    daily_returns: list[float]
    cumulative_returns: list[float] = Field(
        ..., description="Compounded series rebased to 0 at the first date."
    )


class BenchmarkStats(BaseModel):
    name: str
    period_return: float | None = None
    vol_annualised: float | None = None
    max_drawdown: float | None = None


class BenchmarkComparison(BaseModel):
    """Overlay a portfolio's daily metrics against a benchmark."""

    portfolio_name: str
    benchmark_name: str
    dates: list[date]
    portfolio_cumulative_returns: list[float | None]
    benchmark_cumulative_returns: list[float | None]
    portfolio_stats: BenchmarkStats
    benchmark_stats: BenchmarkStats

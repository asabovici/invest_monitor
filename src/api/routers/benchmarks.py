"""HTTP routes for benchmarks (slice 5)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.deps import data_dir_dep
from src.api.schemas.benchmark import (
    BenchmarkComparison,
    BenchmarkInfo,
    BenchmarkReturnsSeries,
    BenchmarkStats,
)
from src.services import benchmarks as benchmarks_service

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.get("", response_model=list[BenchmarkInfo])
def list_benchmarks() -> list[BenchmarkInfo]:
    """Catalogue of named benchmark portfolios."""
    return benchmarks_service.list_benchmarks()


@router.get("/{name:path}/returns", response_model=BenchmarkReturnsSeries)
def get_benchmark_returns(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
    start: Annotated[date | None, Query()] = None,
) -> BenchmarkReturnsSeries:
    """Daily + cumulative returns for one benchmark. 404 if unknown."""
    try:
        return benchmarks_service.benchmark_returns(data_dir, name, start=start)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{name:path}/stats", response_model=BenchmarkStats)
def get_benchmark_stats(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
    start: Annotated[date | None, Query()] = None,
) -> BenchmarkStats:
    """Period return, annualised vol, max drawdown."""
    try:
        return benchmarks_service.benchmark_stats(data_dir, name, start=start)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{name:path}/compare/{portfolio_name}",
    response_model=BenchmarkComparison,
)
def compare_to_benchmark(
    name: str,
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
    start: Annotated[date | None, Query()] = None,
) -> BenchmarkComparison:
    """Overlay a portfolio's persisted cumulative-return series against a benchmark.

    404 on missing benchmark or portfolio.
    """
    try:
        return benchmarks_service.compare_to_benchmark(
            data_dir, portfolio_name, name, start=start,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

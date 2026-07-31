"""HTTP routes for benchmarks (slice 5).

The ``:path`` converter on ``name`` is required so benchmark slugs that
contain a forward slash (e.g. ``60/40 Classic``) survive URL routing.
Every benchmark route ends with a fixed suffix (``/returns``, ``/stats``,
``/compare/{portfolio_name}``), so there's no parsing ambiguity.

Service-layer ValueErrors are translated to 404/400 by the global handler
in ``src.api.errors``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.deps import data_dir_dep
from src.services.schemas.benchmark import (
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
    return benchmarks_service.benchmark_returns(data_dir, name, start=start)


@router.get("/{name:path}/stats", response_model=BenchmarkStats)
def get_benchmark_stats(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
    start: Annotated[date | None, Query()] = None,
) -> BenchmarkStats:
    """Period return, annualised vol, max drawdown. 404 if unknown."""
    return benchmarks_service.benchmark_stats(data_dir, name, start=start)


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
    return benchmarks_service.compare_to_benchmark(
        data_dir, portfolio_name, name, start=start,
    )

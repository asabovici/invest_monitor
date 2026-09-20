"""HTTP route for rebased price history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.deps import data_dir_dep
from src.services import performance as performance_service
from src.services.schemas.performance import PerformanceReport

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("", response_model=PerformanceReport)
def get_performance(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    portfolio: Annotated[
        str | None, Query(description="Scope to one portfolio; omit for all.")
    ] = None,
    start: Annotated[
        str | None, Query(description="ISO date; trims the window. Omit for all history.")
    ] = None,
) -> PerformanceReport:
    """Cumulative return per holding plus the value-weighted portfolio blend.

    Series are rebased to each ticker's own first sample, so a holding that
    starts mid-window still begins at 0% rather than jumping.
    """
    return performance_service.get_performance(data_dir, portfolio, start)

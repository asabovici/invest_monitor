"""HTTP route for the aggregate dashboard snapshot.

One GET feeds the whole Dashboard screen — see ``src.services.dashboard``
for why the aggregation is server-side.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.deps import data_dir_dep
from src.services import dashboard as dashboard_service
from src.services.schemas.dashboard import DashboardSnapshot

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSnapshot)
def get_dashboard(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    start: Annotated[str, Query(description="First date of the value series, YYYY-MM-DD.")] = "2021-05-14",
    portfolio: Annotated[
        str | None, Query(description="Scope to one portfolio; omit for all.")
    ] = None,
) -> DashboardSnapshot:
    """Totals, breakdowns, weekly value series, and priced holdings.

    The series is current holdings valued at historical prices — a
    constant-holdings view, not a record of past balances.
    """
    return dashboard_service.get_snapshot(data_dir, start, portfolio)

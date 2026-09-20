"""HTTP route for portfolio risk and Monte Carlo projection."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.deps import data_dir_dep
from src.services import risk as risk_service
from src.services.schemas.risk import RiskReport

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("", response_model=RiskReport)
def get_risk(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    years: Annotated[float, Query(gt=0, le=60)] = 20.0,
    goal_amount: Annotated[float | None, Query(ge=0)] = None,
    monthly_contribution: Annotated[float, Query(ge=0)] = 0.0,
    num_simulations: Annotated[int, Query(ge=100, le=20000)] = 2000,
    portfolio: Annotated[
        str | None, Query(description="Scope to one portfolio; omit for all.")
    ] = None,
) -> RiskReport:
    """Trailing risk metrics plus a forward Monte Carlo projection.

    The projection assumes i.i.d. normal daily returns fitted to history,
    which understates tail risk — the bands are a spread of plausible
    outcomes, not a confidence interval.
    """
    return risk_service.get_risk(
        data_dir, years, goal_amount, monthly_contribution, num_simulations,
        portfolio,
    )

"""HTTP routes for portfolio reports (slice 4).

Five read-only endpoints, one per report kind, all keyed on
``/{portfolio_name}``. Missing portfolios surface as 404.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.deps import data_dir_dep
from src.api.schemas.report import (
    AttributionReport,
    CorrelationReport,
    ExposureReport,
    IncomeProjectionReport,
    RiskMetricsReport,
)
from src.services import reports as reports_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/risk/{portfolio_name}", response_model=RiskMetricsReport)
def risk_report(
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> RiskMetricsReport:
    """Vol, daily 95% VaR (hist + MC), covariance + correlation matrices."""
    try:
        return reports_service.risk_metrics(data_dir, portfolio_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/exposure/{portfolio_name}", response_model=ExposureReport)
def exposure_report(
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> ExposureReport:
    """Cost-basis exposure grouped by ``(asset_type, sector)``."""
    try:
        return reports_service.exposure(data_dir, portfolio_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/income/{portfolio_name}", response_model=IncomeProjectionReport)
def income_report(
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> IncomeProjectionReport:
    """Annual + monthly income projection per position."""
    try:
        return reports_service.income_projection(data_dir, portfolio_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/correlation/{portfolio_name}", response_model=CorrelationReport)
def correlation_report(
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> CorrelationReport:
    """Pairwise correlation matrix of the portfolio's tickers."""
    try:
        return reports_service.correlation_matrix(data_dir, portfolio_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/attribution/{portfolio_name}", response_model=AttributionReport)
def attribution_report(
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
    start: Annotated[date | None, Query(description="ISO date; window start.")] = None,
    end: Annotated[date | None, Query(description="ISO date; window end inclusive.")] = None,
    top_n: Annotated[int, Query(ge=1, le=50)] = 5,
) -> AttributionReport:
    """Performance attribution over a date range. Pre-refreshed metrics only."""
    try:
        return reports_service.attribution(
            data_dir, portfolio_name, start=start, end=end, top_n=top_n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

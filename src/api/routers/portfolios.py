"""HTTP routes for portfolio reads (slice 1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import data_dir_dep
from src.api.schemas.portfolio import PortfolioDetail, PortfolioSummary
from src.services import portfolios as portfolios_service

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.get("", response_model=list[PortfolioSummary])
def list_portfolios(
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> list[PortfolioSummary]:
    """List all portfolios in the active data dir, newest-first."""
    return portfolios_service.list_portfolios(data_dir)


@router.get("/{name}", response_model=PortfolioDetail)
def get_portfolio(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> PortfolioDetail:
    """Return one portfolio with all positions."""
    try:
        return portfolios_service.get_portfolio(data_dir, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

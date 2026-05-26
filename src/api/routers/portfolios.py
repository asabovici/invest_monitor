"""HTTP routes for portfolios (slices 1 + 2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.api.deps import data_dir_dep
from src.api.schemas.portfolio import (
    CreatePortfolioRequest,
    LoadCsvRequest,
    PortfolioDetail,
    PortfolioSummary,
    UpdatePositionsRequest,
)
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


@router.post(
    "",
    response_model=PortfolioDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_portfolio(
    body: CreatePortfolioRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> PortfolioDetail:
    """Create an empty portfolio. 409 if a portfolio with that name exists."""
    try:
        return portfolios_service.create_portfolio(data_dir, body.name)
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_409_CONFLICT if "already exists" in msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from exc


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> Response:
    """Delete a portfolio. 404 if it does not exist."""
    try:
        portfolios_service.delete_portfolio(data_dir, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/load-csv", response_model=PortfolioDetail, status_code=status.HTTP_201_CREATED)
def load_portfolio_from_csv(
    body: LoadCsvRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> PortfolioDetail:
    """Upsert a portfolio from CSV text. Replaces positions if the portfolio exists."""
    try:
        return portfolios_service.load_portfolio_from_csv(data_dir, body.name, body.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{name}/positions", response_model=PortfolioDetail)
def update_positions(
    name: str,
    body: UpdatePositionsRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> PortfolioDetail:
    """Replace all positions for a portfolio. 404 if portfolio missing."""
    try:
        return portfolios_service.update_positions(data_dir, name, body.positions)
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if "does not exist" in msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from exc

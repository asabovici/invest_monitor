"""HTTP routes for portfolios (slices 1 + 2).

Per-route ``try/except ValueError`` blocks are not needed — the global
handler registered in ``src.api.errors`` translates service-layer
``ValueError``s to the right HTTP status based on the message phrasing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from src.api.deps import data_dir_dep
from src.services.schemas.group import SetPortfolioGroupsRequest
from src.services.schemas.portfolio import (
    CreatePortfolioRequest,
    LoadCsvRequest,
    PortfolioDetail,
    PortfolioSummary,
    UpdatePositionsRequest,
)
from src.services.schemas.trade import TradeList
from src.services import groups as groups_service
from src.services import portfolios as portfolios_service
from src.services import trades as trades_service

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
    """Return one portfolio with all positions. 404 if missing."""
    return portfolios_service.get_portfolio(data_dir, name)


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
    return portfolios_service.create_portfolio(data_dir, body.name)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> Response:
    """Delete a portfolio. 404 if it does not exist."""
    portfolios_service.delete_portfolio(data_dir, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/load-csv", response_model=PortfolioDetail, status_code=status.HTTP_201_CREATED)
def load_portfolio_from_csv(
    body: LoadCsvRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> PortfolioDetail:
    """Upsert a portfolio from CSV text. Replaces positions if the portfolio exists.

    Request body is capped at the server-wide limit configured in
    ``src.api.middleware`` (default 10 MB) to keep oversized uploads from
    pinning a worker.
    """
    return portfolios_service.load_portfolio_from_csv(data_dir, body.name, body.csv_text)


@router.put("/{name}/positions", response_model=PortfolioDetail)
def update_positions(
    name: str,
    body: UpdatePositionsRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> PortfolioDetail:
    """Replace all positions for a portfolio. 404 if portfolio missing."""
    return portfolios_service.update_positions(data_dir, name, body.positions)


# ── Related-resource convenience endpoints ──────────────────────────────────


@router.get("/{name}/groups", response_model=list[str])
def get_portfolio_groups(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> list[str]:
    """Groups containing this portfolio. 404 if portfolio missing."""
    return groups_service.get_groups_for_portfolio(data_dir, name)


@router.put("/{name}/groups", response_model=list[str])
def set_portfolio_groups(
    name: str,
    body: SetPortfolioGroupsRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> list[str]:
    """Replace the group memberships for this portfolio. 400 on unknown groups."""
    return groups_service.set_groups_for_portfolio(data_dir, name, body.group_names)


@router.get("/{name}/trades", response_model=TradeList)
def get_portfolio_trades(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> TradeList:
    """Trade ledger for this portfolio, newest-first."""
    return trades_service.list_trades(data_dir, portfolio_name=name)

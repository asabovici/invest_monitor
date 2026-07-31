"""HTTP routes for the trade ledger (slice 6)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.api.deps import data_dir_dep
from src.services import trades as trades_service
from src.services.schemas.trade import RecordTradeRequest, TradeList

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=TradeList)
def list_trades(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    portfolio_name: Annotated[
        str | None,
        Query(description="Filter to one portfolio. Omit for all trades."),
    ] = None,
) -> TradeList:
    """List trades newest-first. 404 if filter portfolio doesn't exist."""
    return trades_service.list_trades(data_dir, portfolio_name=portfolio_name)


@router.post("", response_model=TradeList, status_code=status.HTTP_201_CREATED)
def record_trade(
    body: RecordTradeRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> TradeList:
    """Append a BUY/SELL trade and apply it to positions.

    Returns the updated trade list for the affected portfolio so the
    client can refresh in one round-trip.
    """
    return trades_service.record_trade(data_dir, body)

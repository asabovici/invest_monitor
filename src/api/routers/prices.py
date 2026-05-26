"""HTTP routes for prices (slice 3)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.deps import data_dir_dep
from src.api.schemas.price import (
    CollectPricesRequest,
    CollectionResult,
    LatestPriceResponse,
    PriceHistory,
)
from src.services import prices as prices_service

router = APIRouter(prefix="/prices", tags=["prices"])


def _parse_tickers(raw: str) -> list[str]:
    """Split a comma-separated ?tickers= query into a deduped, ordered list."""
    seen: set[str] = set()
    out: list[str] = []
    for t in (raw or "").split(","):
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    if not out:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one ticker is required (comma-separated).",
        )
    return out


@router.get("/latest", response_model=LatestPriceResponse)
def get_latest_prices(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    tickers: Annotated[str, Query(description="Comma-separated tickers, e.g. AAPL,MSFT")],
) -> LatestPriceResponse:
    """Latest stored close per ticker. Missing tickers map to null."""
    return prices_service.get_latest_prices(data_dir, _parse_tickers(tickers))


@router.get("/history", response_model=PriceHistory)
def get_price_history(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    tickers: Annotated[str, Query(description="Comma-separated tickers")],
    start: Annotated[
        date | None,
        Query(description="ISO date; only samples on/after this date are returned."),
    ] = None,
) -> PriceHistory:
    """Aligned-date price history for one or more tickers."""
    return prices_service.get_price_history(data_dir, _parse_tickers(tickers), start=start)


@router.post("/collect", response_model=CollectionResult)
def collect_prices(
    body: CollectPricesRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> CollectionResult:
    """Fetch prices from yfinance and store them. 404 if portfolio_name is unknown."""
    try:
        return prices_service.collect_prices(
            data_dir, period=body.period, portfolio_name=body.portfolio_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

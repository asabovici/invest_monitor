"""Pydantic schemas for trade endpoints (slice 6)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


TradeSide = Literal["BUY", "SELL"]


class TradeRow(BaseModel):
    """One row in the trade ledger as exposed to clients."""

    trade_id: int
    portfolio_name: str
    ticker: str
    side: TradeSide
    quantity: float
    trade_price: float
    trade_date: date


class TradeList(BaseModel):
    """List wrapper so we can add pagination metadata later without
    breaking clients that introspect the response shape."""

    trades: list[TradeRow]


class RecordTradeRequest(BaseModel):
    """Body for ``POST /trades``.

    Quantity is **always positive**; ``side`` indicates direction. The
    service applies BUY (average-cost blending) or SELL (FIFO reduction)
    semantics on top of the trade ledger.
    """

    portfolio_name: str = Field(..., min_length=1)
    ticker: str = Field(..., min_length=1)
    side: TradeSide
    quantity: float = Field(..., gt=0)
    trade_price: float = Field(..., gt=0)
    trade_date: date

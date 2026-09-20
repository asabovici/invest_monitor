"""Schemas for the dashboard snapshot.

One endpoint feeds the whole Dashboard screen. Composing it client-side
would mean a price-history request per holding — dozens of round trips for
a single page load — so the aggregation happens server-side and ships as a
single typed payload.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Holding(BaseModel):
    """One position, priced at the latest stored close."""

    ticker: str
    name: str = Field(
        default="",
        description="Display name from the security master; falls back to the ticker.",
    )
    account: str
    asset_type: str
    quantity: float
    price: float
    market_value: float
    cost: float

    @property
    def gain(self) -> float:
        return self.market_value - self.cost


class ValueSeries(BaseModel):
    """Portfolio value over time, weekly.

    ``by_type`` is keyed by asset type and aligned to ``dates``, so the
    client can stack without re-aligning.

    This is **current holdings valued at historical prices** — a
    constant-holdings series. It is not a record of past balances, because
    positions carry no time dimension (see ``services.datafix``). The field
    name and this docstring are the contract; don't relabel it "net worth
    history" in a client.
    """

    dates: list[str]
    total: list[float]
    by_type: dict[str, list[float]]


class DashboardSnapshot(BaseModel):
    """Everything the Dashboard screen renders."""

    market_value: float
    cost: float
    gain: float
    asset_type_order: list[str] = Field(
        description="Stable stacking / colour order. Clients must not re-sort "
        "this — chart colour follows the asset type, never its rank."
    )
    totals_by_type: dict[str, float]
    totals_by_account: dict[str, float]
    series: ValueSeries
    holdings: list[Holding]
    unpriced: list[str] = Field(
        default_factory=list,
        description="Tickers with no usable price; excluded from all totals.",
    )


__all__ = ["Holding", "ValueSeries", "DashboardSnapshot"]

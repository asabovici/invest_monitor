"""Pydantic schemas for price endpoints (slice 3)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class LatestPriceResponse(BaseModel):
    """Latest stored price per ticker — keyed by ticker.

    Tickers with no recorded prices may map to ``None`` (no data at all)
    or to ``1.0`` (data layer's cash-style backfill — Cash and CD assets
    are held at par, and unknown tickers fall through that same path).
    Clients that care about the distinction should call ``/prices/history``
    and inspect whether any non-1.0 sample exists.
    """

    prices: dict[str, float | None]


class PriceHistory(BaseModel):
    """Aligned-date price history for one or more tickers.

    ``dates`` is one ascending list of ISO dates. For each ticker,
    ``prices[ticker]`` is the same length as ``dates`` — missing samples
    become ``None`` rather than being skipped, so consumers can rebuild
    a DataFrame without re-aligning.
    """

    tickers: list[str]
    dates: list[date]
    prices: dict[str, list[float | None]]


class CollectPricesRequest(BaseModel):
    """Body for ``POST /prices/collect``."""

    period: str = Field(
        "1y",
        description="yfinance period (e.g. 1mo, 3mo, 6mo, 1y, 2y, 5y, max).",
    )
    portfolio_name: str | None = Field(
        None,
        description="If set, collect only the tickers held in this portfolio. "
                    "Otherwise collect prices for every asset in the database.",
    )


class CollectionResult(BaseModel):
    """Outcome of a ``collect_prices`` call.

    ``tickers_collected`` lists tickers that successfully wrote at least
    one row. ``tickers_failed`` maps ticker → error message for any that
    threw or returned an empty DataFrame.
    """

    tickers_collected: list[str]
    tickers_failed: dict[str, str]

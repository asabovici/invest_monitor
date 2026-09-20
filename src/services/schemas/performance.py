"""Schemas for the Performance screen."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TickerSeries(BaseModel):
    """One ticker's normalised history, aligned to the report's ``dates``."""

    ticker: str
    asset_type: str
    market_value: float
    # Index-for-index with PerformanceReport.dates. None where the ticker
    # has no sample on that date — the series starts later than the window.
    cumulative_return: list[float | None] = Field(
        ..., description="Decimal return since the ticker's first sample. 0.0 at its start."
    )
    total_return: float = Field(..., description="Decimal return over the whole window.")


class PerformanceReport(BaseModel):
    """Rebased price history for every priced holding in scope."""

    dates: list[str] = Field(..., description="Ascending ISO dates, shared x-axis.")
    series: list[TickerSeries] = Field(..., description="Sorted by market value, largest first.")
    portfolio_cumulative_return: list[float | None] = Field(
        ..., description="Value-weighted blend of the series, aligned to ``dates``."
    )
    portfolio_total_return: float
    excluded: list[str] = Field(
        ..., description="Tickers with no usable price history; absent from every series."
    )

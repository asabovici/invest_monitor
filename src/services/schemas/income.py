"""Schemas for portfolio-wide income projection."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IncomeHolding(BaseModel):
    """Projected income from one position."""

    ticker: str
    name: str
    account: str
    asset_type: str
    market_value: float
    annual_income: float
    monthly_income: float
    yield_pct: float = Field(description="Annual income as a percent of market value.")
    payment_frequency: int


class IncomeBucket(BaseModel):
    """Income grouped by some dimension."""

    label: str
    annual_income: float
    market_value: float
    yield_pct: float


class IncomeReport(BaseModel):
    """Everything the Income screen renders."""

    market_value: float
    annual_income: float
    monthly_income: float
    portfolio_yield_pct: float
    by_asset_type: list[IncomeBucket]
    by_account: list[IncomeBucket]
    holdings: list[IncomeHolding]
    non_income_value: float = Field(
        description="Market value of holdings projected to pay nothing."
    )
    non_income_tickers: list[str] = Field(
        default_factory=list,
        description=(
            "Holdings with no income rate on record. Some genuinely pay nothing; "
            "others may simply be missing a rate, so the total is a floor."
        ),
    )


__all__ = ["IncomeHolding", "IncomeBucket", "IncomeReport"]

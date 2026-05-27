"""Pydantic schemas for report endpoints (slice 4).

All five reports take ``(data_dir, portfolio_name, …)`` at the service
layer and surface as ``GET /reports/{kind}/{portfolio_name}`` over HTTP.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


# ── Risk ─────────────────────────────────────────────────────────────────────


class RiskMetricsReport(BaseModel):
    """Portfolio-level risk headline.

    All return-like figures are **decimals** (0.15 = 15%), to match the
    convention in ``src/reporting.py``. Multiply by 100 only at the UI.
    VaR values are at the daily horizon, 95% confidence; multiply by
    ``sqrt(days)`` for longer windows.
    """

    portfolio_name: str
    annualised_volatility: float = Field(..., description="σ × √252, decimal")
    historical_var_95: float = Field(..., description="Daily 95% VaR, decimal")
    monte_carlo_var_95: float = Field(..., description="Daily 95% VaR, decimal")
    tickers: list[str]
    covariance_matrix: dict[str, dict[str, float]] = Field(
        ..., description="Annualised covariance — keyed [ticker_a][ticker_b]."
    )
    correlation_matrix: dict[str, dict[str, float]] = Field(
        ..., description="Pearson correlation of daily returns, [a][b]."
    )


# ── Exposure ─────────────────────────────────────────────────────────────────


class ExposureRow(BaseModel):
    asset_type: str
    sector: str | None = None
    market_value: float = Field(
        ...,
        description="Σ qty × cost_basis_per_share for rows in this (type, sector) bucket. "
                    "Matches the existing dashboard's cost-basis view.",
    )
    weight_pct: float = Field(..., description="Bucket share of portfolio total, percent.")


class ExposureReport(BaseModel):
    portfolio_name: str
    total_value: float
    rows: list[ExposureRow]


# ── Income ───────────────────────────────────────────────────────────────────


class IncomeProjectionRow(BaseModel):
    ticker: str
    asset_type: str
    base_value: float
    income_rate: float
    income_rate_unit: str = Field(..., description="$/share/payment or %")
    annual_income: float
    monthly_income: float
    payment_frequency: int
    yield_on_base_pct: float


class IncomeProjectionReport(BaseModel):
    portfolio_name: str
    rows: list[IncomeProjectionRow]
    total_annual_income: float
    total_monthly_income: float


# ── Correlation ──────────────────────────────────────────────────────────────


class CorrelationReport(BaseModel):
    portfolio_name: str
    tickers: list[str]
    matrix: dict[str, dict[str, float]]


# ── Attribution ──────────────────────────────────────────────────────────────


class AttributionContributor(BaseModel):
    """One row in the top-contributors / detractors tables."""

    ticker: str
    contribution_to_return: float = Field(
        ..., description="Sum of daily contribution_to_return over the window, decimal."
    )
    average_weight: float = Field(..., description="Mean weight over the window, decimal.")


class AttributionReport(BaseModel):
    """Performance attribution over a date range.

    Pulls from pre-computed ``daily_portfolio_metrics`` and
    ``daily_attribution`` parquet — refresh those via the existing
    ``invest-monitor metrics refresh`` job before calling.
    """

    portfolio_name: str
    start_date: date
    end_date: date
    cumulative_return: float = Field(..., description="Decimal, e.g. 0.085 = +8.5%")
    max_drawdown: float = Field(..., description="Largest peak-to-trough drawdown in the window, decimal.")
    dates: list[date]
    daily_returns: list[float | None]
    top_contributors: list[AttributionContributor]
    top_detractors: list[AttributionContributor]

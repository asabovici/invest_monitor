"""Schemas for portfolio risk and Monte Carlo projection."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskMetrics(BaseModel):
    """Backward-looking risk, measured on the portfolio's own return history."""

    annualised_volatility: float = Field(description="σ × √252, as a decimal.")
    historical_var_95: float = Field(
        description="Worst 5th-percentile daily return, as a negative decimal."
    )
    monte_carlo_var_95: float = Field(
        description="5th-percentile daily return under a fitted normal, negative."
    )
    historical_var_99: float = Field(
        description="Worst 1st-percentile daily return, as a negative decimal."
    )
    expected_shortfall_95: float = Field(
        description=(
            "Mean daily return among the worst 5% of days, negative. VaR gives "
            "the threshold; this gives the average loss once it is breached, so "
            "it is the figure that moves when the tail is fat."
        )
    )
    expected_shortfall_99: float = Field(
        description="Mean daily return among the worst 1% of days, negative."
    )
    max_drawdown: float = Field(description="Deepest peak-to-trough fall, negative.")
    current_drawdown: float = Field(
        description="Fall from the running peak as at the last observation, negative or 0."
    )
    best_day: float
    worst_day: float
    observations: int = Field(description="Trading days of history behind these figures.")


class ProjectionBands(BaseModel):
    """Percentile bands of simulated value over time.

    Each list is aligned to ``dates``, so a client can draw a fan chart
    without re-aligning anything.
    """

    dates: list[str]
    p5: list[float]
    p25: list[float]
    p50: list[float]
    p75: list[float]
    p95: list[float]


class Projection(BaseModel):
    """Forward-looking Monte Carlo projection."""

    years: float
    num_simulations: int
    monthly_contribution: float
    total_contributions: float
    goal_amount: float | None = None
    probability_of_success: float | None = Field(
        default=None, description="Share of paths finishing at or above the goal, 0–1."
    )
    expected_value: float
    final_percentiles: dict[str, float]
    bands: ProjectionBands
    assumed_annual_return: float
    assumed_annual_volatility: float


class RiskReport(BaseModel):
    """Everything the Risk screen renders."""

    market_value: float
    metrics: RiskMetrics
    projection: Projection
    holdings_covered: int = Field(description="Holdings with usable return history.")
    holdings_total: int
    data_notes: list[str] = Field(
        default_factory=list,
        description=(
            "Price glitches excluded from the fit. A spike that reverses within "
            "days is a bad quote, not a return; leaving it in would corrupt every "
            "figure on this screen."
        ),
    )


__all__ = ["RiskMetrics", "ProjectionBands", "Projection", "RiskReport"]

"""Pydantic schemas for portfolio endpoints.

These double as the service-layer return types — see
``src/services/portfolios.py``. Keeping a single set of models avoids
duplicate validation logic; if/when the internal shape needs to diverge
from the wire shape, split into ``PortfolioInternal`` vs
``PortfolioResponse``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PositionView(BaseModel):
    """One row of a portfolio's position table, as exposed to clients."""

    ticker: str
    asset_type: str
    name: str
    sector: str | None = None
    currency: str = "USD"
    quantity: float
    cost_basis_per_share: float = Field(
        ...,
        description="Cost basis is always per share, never total. Total = quantity × cost_basis_per_share.",
    )


class PortfolioSummary(BaseModel):
    """Lightweight portfolio listing entry. No positions inlined."""

    name: str
    position_count: int
    total_cost: float = Field(
        ..., description="Σ(quantity × cost_basis_per_share) across positions."
    )


class PortfolioDetail(BaseModel):
    """Full portfolio with all positions."""

    name: str
    positions: list[PositionView]
    total_cost: float

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


class PositionInput(BaseModel):
    """A position payload accepted by write endpoints.

    ``cost_basis_per_share`` matches the storage convention — never pass
    total cost.

    Asset-side fields (``asset_type``, ``name``, ``sector``, ``currency``)
    are used to upsert the row in the assets table before the position is
    saved. If the asset already exists, repeat-supplied values overwrite
    the stored metadata (idempotent upsert).

    ``asset_type`` accepts any value of ``src.models.AssetType``
    (``Stock``, ``Bond``, ``ETF``, ``Fund``, ``Cash``, ``CD``, ``Crypto``).
    """

    ticker: str
    quantity: float = Field(..., gt=0)
    cost_basis_per_share: float = Field(..., ge=0)
    asset_type: str = "Stock"
    name: str | None = None
    sector: str | None = None
    currency: str = "USD"


class CreatePortfolioRequest(BaseModel):
    """Body for ``POST /portfolios``."""

    name: str = Field(..., min_length=1)


class UpdatePositionsRequest(BaseModel):
    """Body for ``PUT /portfolios/{name}/positions``.

    Full-replacement semantics: any position not in the payload is removed
    from the portfolio. Empty list clears all positions.
    """

    positions: list[PositionInput]


class LoadCsvRequest(BaseModel):
    """Body for ``POST /portfolios/load-csv``.

    The CSV format matches the existing Ingester: columns ``Ticker``,
    ``Name``, ``Type``, ``Quantity``, ``CostBasis`` (total, will be
    converted to per-share), ``Currency`` (optional), ``Sector`` (optional),
    plus optional ``ConstituentTickers`` / ``ConstituentWeights`` for
    composite assets.
    """

    name: str = Field(..., min_length=1)
    csv_text: str = Field(..., min_length=1)

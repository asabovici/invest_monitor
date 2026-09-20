"""Schemas for look-through exposure.

Two breakdowns, deliberately separate:

* **Asset class** covers the whole portfolio — every dollar lands in equity,
  bonds, cash or other.
* **Equity sector** covers only the equity slice, because a bond or commodity
  fund has no sector. Mixing the two would understate every sector weight by
  the size of the fixed-income book.

Both carry a coverage figure so a client can say how much of the portfolio the
breakdown actually explains, rather than implying totality it doesn't have.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Slice(BaseModel):
    """One bucket of a breakdown."""

    label: str
    value: float
    weight: float = Field(description="Share of the breakdown's own base, 0–1.")


class Contributor(BaseModel):
    """A holding's contribution to one bucket."""

    ticker: str
    name: str
    value: float


class Breakdown(BaseModel):
    """A full breakdown plus what it does and doesn't explain."""

    slices: list[Slice]
    base: float = Field(description="Total value this breakdown divides up.")
    covered: float = Field(description="Portion of `base` that could be classified.")
    unclassified: float = 0.0
    top_contributors: dict[str, list[Contributor]] = Field(
        default_factory=dict,
        description="Per bucket label, the largest holdings feeding it.",
    )


class ExposureReport(BaseModel):
    """Look-through exposure across the whole portfolio."""

    market_value: float
    by_asset_class: Breakdown
    by_sector: Breakdown
    short_equity: float = Field(
        default=0.0,
        description=(
            "Negative equity exposure from inverse funds, as a positive number. "
            "It reduces the Equity asset class but cannot be allocated to "
            "sectors — the sector base is long equity only, so the two "
            "breakdowns differ by exactly this amount."
        ),
    )
    as_of: str = Field(description="Date of the fund profiles used, YYYY-MM-DD.")
    unprofiled_funds: list[str] = Field(
        default_factory=list,
        description="Funds held with no stored profile — counted as unclassified.",
    )
    renormalised_funds: list[str] = Field(
        default_factory=list,
        description=(
            "Funds whose stored weights did not sum to 1 and were rescaled. "
            "Leveraged and inverse funds legitimately report >100%."
        ),
    )


__all__ = ["Slice", "Contributor", "Breakdown", "ExposureReport"]

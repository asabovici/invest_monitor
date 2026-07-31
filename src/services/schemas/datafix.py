"""Schemas for the data-correction service.

Every mutating operation in ``src.services.datafix`` is two-phase: a
``preview_*`` call returns a :class:`ChangePreview` and writes nothing, then
``apply_change`` commits it. These models are the contract between the two
phases and are what the data agent's skills serialise back to the model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["error", "warning", "info"]
RowOp = Literal["update", "insert", "delete"]
FixDomain = Literal["positions", "trades", "assets", "prices", "fund_holdings"]


class FieldChange(BaseModel):
    """One column moving from ``before`` to ``after`` on a single row."""

    field: str
    before: Any = None
    after: Any = None


class RowChange(BaseModel):
    """A row-level edit, identified by a human-readable key.

    ``key`` is meant to be readable in a chat transcript — ``"Demo Brokerage /
    PRU"`` rather than a positional index — because the agent shows these
    diffs to a human who is deciding whether to approve them.
    """

    key: str
    op: RowOp
    fields: list[FieldChange] = Field(default_factory=list)


class ChangePreview(BaseModel):
    """A staged, not-yet-written change.

    Holds everything a reviewer needs to say yes or no. ``warnings`` carries
    anything suspicious that is not fatal — a cost basis moving by more than
    an order of magnitude, a fill-forward run longer than a week — so the
    reviewer sees the risk rather than having to infer it from the diff.
    """

    change_id: str
    domain: FixDomain
    summary: str
    target: str
    rows_changed: int = 0
    rows_added: int = 0
    rows_removed: int = 0
    changes: list[RowChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApplyResult(BaseModel):
    """Outcome of committing a staged change."""

    change_id: str
    domain: FixDomain
    summary: str
    backup_path: str
    audit_path: str
    rows_written: int


class Issue(BaseModel):
    """One problem found by :func:`scan_data_issues`.

    ``suggested_fix`` names the preview function that would address it, so the
    agent can move from diagnosis to a concrete proposal without guessing.
    """

    severity: Severity
    domain: FixDomain
    key: str
    detail: str
    suggested_fix: str | None = None


class ScanReport(BaseModel):
    """Everything the integrity scan found, worst first."""

    data_dir: str
    issues: list[Issue] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class PriceGap(BaseModel):
    """A run of missing business days in one ticker's price series."""

    ticker: str
    start: str
    end: str
    missing_days: int


__all__ = [
    "FieldChange",
    "RowChange",
    "ChangePreview",
    "ApplyResult",
    "Issue",
    "ScanReport",
    "PriceGap",
    "Severity",
    "RowOp",
    "FixDomain",
]

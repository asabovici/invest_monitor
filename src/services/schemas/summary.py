"""Pydantic schemas for conversation-summary endpoints (slice 7)."""

from __future__ import annotations

from pydantic import BaseModel


class SummaryInfo(BaseModel):
    """One row in the summary listing — no transcript inlined."""

    key: str
    agent: str
    started_at: str
    summary: str
    message_count: int


class SummaryTurn(BaseModel):
    """One turn of a persisted transcript."""

    role: str
    content: str


class SummaryDetail(SummaryInfo):
    """Full summary detail including the saved transcript."""

    transcript: list[SummaryTurn]


class SaveSummaryRequest(BaseModel):
    """Body for ``POST /summaries/from-session``."""

    session_id: str

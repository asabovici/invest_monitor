"""HTTP routes for conversation summaries (slice 7)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from src.api.deps import data_dir_dep
from src.services import summaries as summaries_service
from src.services.schemas.summary import (
    SaveSummaryRequest,
    SummaryDetail,
    SummaryInfo,
)

router = APIRouter(prefix="/summaries", tags=["summaries"])


@router.get("", response_model=list[SummaryInfo])
def list_summaries(
    data_dir: Annotated[str, Depends(data_dir_dep)],
    agent: Annotated[
        str | None,
        Query(description="Filter to one kind: risk / wealth / research / pm / cio."),
    ] = None,
) -> list[SummaryInfo]:
    """All saved summaries newest first, optionally filtered by agent kind."""
    return summaries_service.list_summaries(data_dir, agent=agent)


@router.get("/{key}", response_model=SummaryDetail)
def get_summary(
    key: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> SummaryDetail:
    """One summary with its full transcript. 404 if unknown."""
    return summaries_service.get_summary(data_dir, key)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_summary(
    key: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> Response:
    """Delete one summary. 404 if missing."""
    summaries_service.delete_summary(data_dir, key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/from-session",
    response_model=SummaryDetail,
    status_code=status.HTTP_201_CREATED,
)
def save_from_session(
    body: SaveSummaryRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> SummaryDetail:
    """Compress an open session's transcript via Haiku and persist it.

    400 on empty conversation; 404 on unknown session.
    """
    return summaries_service.save_summary_from_session(data_dir, body.session_id)

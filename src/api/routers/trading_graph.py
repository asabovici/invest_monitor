"""HTTP routes for the LangGraph trading-coordination runs (slice 8)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from src.services import trading_graph as graph_service
from src.services.schemas.trading_graph import (
    ResumeRunRequest,
    RunState,
    StartRunRequest,
)

router = APIRouter(prefix="/trading-graph", tags=["trading-graph"])


@router.post(
    "/runs",
    response_model=RunState,
    status_code=status.HTTP_201_CREATED,
)
def start_run(body: StartRunRequest | None = None) -> RunState:
    """Start a new run.

    With ``settings.human_in_the_loop=True`` (the default) the graph
    pauses before the CIO node; the response captures that pause state.
    With ``human_in_the_loop=False`` the run completes inline and the
    response is the terminal state.
    """
    settings_schema = body.settings if body else None
    return graph_service.start_run(settings_schema)


@router.get("/runs/{run_id}", response_model=RunState)
def get_run(run_id: str) -> RunState:
    """Current snapshot for a run. 404 if unknown."""
    return graph_service.get_run_state(run_id)


@router.post("/runs/{run_id}/resume", response_model=RunState)
def resume_run(run_id: str, body: ResumeRunRequest | None = None) -> RunState:
    """Resume from the current interrupt, optionally patching state first.

    Pass ``state_patch`` to override ``proposed_trades``, append to
    ``risk_critique``, etc. before the CIO acts. 404 if the run is unknown.
    """
    patch = body.state_patch if body else None
    return graph_service.resume_run(run_id, state_patch=patch)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def end_run(run_id: str) -> Response:
    """Drop a run record. 404 if missing."""
    graph_service.end_run(run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""HTTP routes for agent chat sessions (slice 7).

Service-layer ValueErrors map to 404/400 via the global handler.
Anthropic API errors raised on first message surface as 500 (default).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from src.api.deps import data_dir_dep
from src.services import agents as agents_service
from src.services.schemas.agent import (
    AgentKind,
    ChatHistory,
    ChatMessageRequest,
    ChatReply,
    ChatSession,
    PrimeChatRequest,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/kinds", response_model=list[str])
def list_kinds() -> list[str]:
    """The 5 supported agent kinds: risk / wealth / research / pm / cio."""
    return agents_service.known_kinds()


@router.post(
    "/{kind}/sessions",
    response_model=ChatSession,
    status_code=status.HTTP_201_CREATED,
)
def start_session(
    kind: AgentKind,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> ChatSession:
    """Open a new chat session for ``kind``. Agent constructed lazily."""
    return agents_service.start_chat(kind, data_dir)


@router.get("/sessions/{session_id}", response_model=ChatSession)
def get_session(session_id: str) -> ChatSession:
    """Session metadata (created_at, message_count). 404 if unknown."""
    return agents_service.get_session(session_id)


@router.get("/sessions/{session_id}/history", response_model=ChatHistory)
def get_history(session_id: str) -> ChatHistory:
    """Full transcript for the session — empty until the first message."""
    return agents_service.get_history(session_id)


@router.post("/sessions/{session_id}/messages", response_model=ChatReply)
def send_message(
    session_id: str,
    body: ChatMessageRequest,
) -> ChatReply:
    """Send one user message and return the agent's reply text."""
    return agents_service.chat_message(session_id, body.message)


@router.post("/sessions/{session_id}/prime", response_model=ChatReply)
def prime_session(
    session_id: str,
    body: PrimeChatRequest,
) -> ChatReply:
    """Prime the session with past conversation summaries (one or more keys)."""
    return agents_service.prime_chat(session_id, body.summary_keys)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def end_session(session_id: str) -> Response:
    """Drop a session from the cache. 404 if unknown."""
    agents_service.end_chat(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Pydantic schemas for agent (chat session) endpoints (slice 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AgentKind = Literal["risk", "wealth", "research", "pm", "cio", "data"]


class ChatSession(BaseModel):
    """Metadata for an open chat session.

    The session itself lives in a server-side cache (see
    ``services.agents``) — clients only carry the ``session_id`` and
    treat it as opaque.
    """

    session_id: str
    kind: AgentKind
    data_dir: str
    created_at: datetime
    message_count: int = 0


class ChatMessageRequest(BaseModel):
    """Body for ``POST /agents/sessions/{id}/messages``."""

    message: str = Field(..., min_length=1)


class ChatReply(BaseModel):
    """Server's reply to a chat message."""

    session_id: str
    reply: str
    message_count: int


class ChatTurn(BaseModel):
    """One turn of the persisted conversation transcript."""

    role: Literal["user", "assistant", "system"]
    content: str


class ChatHistory(BaseModel):
    """Full transcript for a session — used for re-rendering UI state."""

    session_id: str
    kind: AgentKind
    messages: list[ChatTurn]


class PrimeChatRequest(BaseModel):
    """Body for ``POST /agents/sessions/{id}/prime``.

    The service pulls each summary by key from ``agent_summaries.json``,
    builds a single priming prompt, and sends it through the live agent
    as a user message. Returns the agent's acknowledgement.
    """

    summary_keys: list[str] = Field(..., min_length=1)

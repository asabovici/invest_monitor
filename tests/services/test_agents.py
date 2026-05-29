"""Tests for src/services/agents.py with the agent classes stubbed.

Real ``RiskAgent`` / ``WealthAgent`` etc. instantiate
``anthropic.Anthropic()`` (which reads ``ANTHROPIC_API_KEY``) and would
otherwise hit the network. We register a deterministic stub class via
``register_agent_class`` so the cache logic can be exercised hermetically.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.services import agents as agents_service


class _StubClient:
    """Stand-in for ``anthropic.Anthropic`` used in summary tests."""


class _StubAgent:
    """Mirrors the public surface of the real agent classes."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = data_dir
        self.client = _StubClient()
        self.messages: list[dict] = []

    def chat(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        reply = f"echo: {user_input}"
        self.messages.append({"role": "assistant", "content": reply})
        return reply


@pytest.fixture(autouse=True)
def reset_cache_and_register_stub():
    agents_service.reset_sessions()
    # Override every kind with the stub so we never accidentally hit real agents.
    for kind in ("risk", "wealth", "research", "pm", "cio", "stub"):
        agents_service.register_agent_class(kind, _StubAgent)
    yield
    agents_service.reset_sessions()


def test_known_kinds_lists_registered() -> None:
    assert {"risk", "wealth", "research", "pm", "cio"}.issubset(set(agents_service.known_kinds()))


def test_start_chat_returns_session(tmp_path) -> None:
    session = agents_service.start_chat("risk", str(tmp_path))
    assert session.kind == "risk"
    assert session.session_id
    assert session.message_count == 0
    assert isinstance(session.created_at, datetime)


def test_start_chat_unknown_kind_raises() -> None:
    # Build a fresh registry view that doesn't include "bogus".
    with pytest.raises(ValueError, match="Unknown agent kind"):
        agents_service.start_chat("bogus", "data")


def test_chat_message_appends_history(tmp_path) -> None:
    session = agents_service.start_chat("wealth", str(tmp_path))
    r1 = agents_service.chat_message(session.session_id, "hello")
    assert r1.reply == "echo: hello"
    assert r1.message_count == 2  # user + assistant
    r2 = agents_service.chat_message(session.session_id, "again")
    assert r2.message_count == 4


def test_chat_message_empty_raises(tmp_path) -> None:
    session = agents_service.start_chat("risk", str(tmp_path))
    with pytest.raises(ValueError, match="empty"):
        agents_service.chat_message(session.session_id, "   ")


def test_get_history_returns_turns(tmp_path) -> None:
    session = agents_service.start_chat("risk", str(tmp_path))
    agents_service.chat_message(session.session_id, "hi")
    history = agents_service.get_history(session.session_id)
    assert [m.role for m in history.messages] == ["user", "assistant"]
    assert history.messages[1].content == "echo: hi"


def test_end_chat_drops_session(tmp_path) -> None:
    session = agents_service.start_chat("risk", str(tmp_path))
    agents_service.end_chat(session.session_id)
    with pytest.raises(ValueError, match="not found"):
        agents_service.get_session(session.session_id)


def test_end_chat_missing_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        agents_service.end_chat("not-a-real-id")


def test_chat_message_missing_session_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        agents_service.chat_message("nope", "hello")

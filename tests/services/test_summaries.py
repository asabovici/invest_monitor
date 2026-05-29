"""Tests for src/services/summaries.py using the stub agent."""

from __future__ import annotations

import json
import os

import pytest

from src.services import agents as agents_service
from src.services import summaries as summaries_service


class _StubClient:
    pass


class _StubAgent:
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
def stub_agents():
    agents_service.reset_sessions()
    for kind in ("risk", "wealth", "research", "pm", "cio"):
        agents_service.register_agent_class(kind, _StubAgent)
    yield
    agents_service.reset_sessions()


@pytest.fixture(autouse=True)
def stub_summarise(monkeypatch):
    """Avoid calling Anthropic for the summary text."""
    from src import agent_summaries
    monkeypatch.setattr(
        agent_summaries,
        "summarize_conversation",
        lambda messages, agent, **kw: f"stub summary of {len(messages)} msgs",
    )


def _seed_summary(data_dir: str, agent: str = "risk", n_msgs: int = 2) -> str:
    """Create a session, send n_msgs, save the summary, return the key."""
    session = agents_service.start_chat(agent, data_dir)
    for i in range(n_msgs // 2):
        agents_service.chat_message(session.session_id, f"msg {i}")
    detail = summaries_service.save_summary_from_session(data_dir, session.session_id)
    return detail.key


def test_save_summary_from_session_writes_to_disk(tmp_path) -> None:
    data_dir = str(tmp_path)
    key = _seed_summary(data_dir, agent="wealth", n_msgs=4)
    with open(os.path.join(data_dir, "agent_summaries.json")) as f:
        store = json.load(f)
    assert key in store
    assert store[key]["agent"] == "wealth"
    assert store[key]["message_count"] == 4


def test_save_empty_session_raises(tmp_path) -> None:
    session = agents_service.start_chat("risk", str(tmp_path))
    with pytest.raises(ValueError, match="empty"):
        summaries_service.save_summary_from_session(str(tmp_path), session.session_id)


def test_list_summaries_filters_by_agent(tmp_path) -> None:
    data_dir = str(tmp_path)
    _seed_summary(data_dir, agent="risk")
    _seed_summary(data_dir, agent="wealth")
    risk_only = summaries_service.list_summaries(data_dir, agent="risk")
    assert all(s.agent == "risk" for s in risk_only)
    assert len(risk_only) == 1


def test_get_summary_returns_transcript(tmp_path) -> None:
    data_dir = str(tmp_path)
    key = _seed_summary(data_dir, agent="risk", n_msgs=4)
    detail = summaries_service.get_summary(data_dir, key)
    assert detail.key == key
    assert len(detail.transcript) == 4


def test_get_unknown_summary_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        summaries_service.get_summary(str(tmp_path), "no-such-key")


def test_delete_summary(tmp_path) -> None:
    data_dir = str(tmp_path)
    key = _seed_summary(data_dir)
    summaries_service.delete_summary(data_dir, key)
    with pytest.raises(ValueError):
        summaries_service.get_summary(data_dir, key)


def test_delete_unknown_summary_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="not found"):
        summaries_service.delete_summary(str(tmp_path), "no-such")


def test_prime_chat_with_summary_round_trips(tmp_path) -> None:
    data_dir = str(tmp_path)
    key = _seed_summary(data_dir, agent="risk", n_msgs=2)
    new_session = agents_service.start_chat("research", data_dir)
    reply = agents_service.prime_chat(new_session.session_id, [key])
    assert reply.reply.startswith("echo: ")
    # The primer was sent as a user message + the agent answered.
    assert reply.message_count >= 2


def test_prime_chat_unknown_key_raises(tmp_path) -> None:
    session = agents_service.start_chat("risk", str(tmp_path))
    with pytest.raises(ValueError, match="Unknown summary"):
        agents_service.prime_chat(session.session_id, ["not-a-real-key"])

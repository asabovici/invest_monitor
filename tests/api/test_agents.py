"""Tests for /agents and /summaries routes via FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.services import agents as agents_service


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
def stub_agents(monkeypatch):
    agents_service.reset_sessions()
    for kind in ("risk", "wealth", "research", "pm", "cio"):
        agents_service.register_agent_class(kind, _StubAgent)
    # No-op Haiku call for summary-saving paths.
    from src import agent_summaries
    monkeypatch.setattr(
        agent_summaries,
        "summarize_conversation",
        lambda messages, agent, **kw: f"stub summary of {len(messages)} msgs",
    )
    yield
    agents_service.reset_sessions()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def headers(tmp_path) -> dict[str, str]:
    return {"X-Data-Dir": str(tmp_path)}


# ── Sessions ─────────────────────────────────────────────────────────────────


def test_kinds(client: TestClient) -> None:
    r = client.get("/agents/kinds")
    assert r.status_code == 200
    assert {"risk", "wealth", "research", "pm", "cio"}.issubset(set(r.json()))


def test_start_session_201(client: TestClient, headers) -> None:
    r = client.post("/agents/risk/sessions", headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "risk"
    assert body["message_count"] == 0


def test_start_unknown_kind_422(client: TestClient, headers) -> None:
    """Pydantic Literal validation rejects unknown kinds at the route level."""
    r = client.post("/agents/bogus/sessions", headers=headers)
    assert r.status_code == 422


def test_message_flow(client: TestClient, headers) -> None:
    sid = client.post("/agents/wealth/sessions", headers=headers).json()["session_id"]
    r = client.post(
        f"/agents/sessions/{sid}/messages",
        json={"message": "hello"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["reply"].startswith("echo:")
    assert r.json()["message_count"] == 2


def test_history_endpoint(client: TestClient, headers) -> None:
    sid = client.post("/agents/risk/sessions", headers=headers).json()["session_id"]
    client.post(
        f"/agents/sessions/{sid}/messages", json={"message": "hi"}, headers=headers,
    )
    r = client.get(f"/agents/sessions/{sid}/history", headers=headers)
    assert r.status_code == 200
    assert [m["role"] for m in r.json()["messages"]] == ["user", "assistant"]


def test_missing_session_404(client: TestClient, headers) -> None:
    r = client.get("/agents/sessions/no-such", headers=headers)
    assert r.status_code == 404
    r = client.post(
        "/agents/sessions/no-such/messages",
        json={"message": "hi"},
        headers=headers,
    )
    assert r.status_code == 404


def test_empty_message_422(client: TestClient, headers) -> None:
    sid = client.post("/agents/risk/sessions", headers=headers).json()["session_id"]
    r = client.post(
        f"/agents/sessions/{sid}/messages",
        json={"message": ""},
        headers=headers,
    )
    assert r.status_code == 422


def test_end_session_204(client: TestClient, headers) -> None:
    sid = client.post("/agents/risk/sessions", headers=headers).json()["session_id"]
    r = client.delete(f"/agents/sessions/{sid}", headers=headers)
    assert r.status_code == 204
    r2 = client.get(f"/agents/sessions/{sid}", headers=headers)
    assert r2.status_code == 404


# ── Summaries ────────────────────────────────────────────────────────────────


def _seed_summary_via_api(client: TestClient, headers: dict[str, str], kind: str = "risk") -> str:
    sid = client.post(f"/agents/{kind}/sessions", headers=headers).json()["session_id"]
    client.post(
        f"/agents/sessions/{sid}/messages",
        json={"message": "ping"},
        headers=headers,
    )
    r = client.post("/summaries/from-session", json={"session_id": sid}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["key"]


def test_save_summary_via_api(client: TestClient, headers) -> None:
    key = _seed_summary_via_api(client, headers, "wealth")
    r = client.get(f"/summaries/{key}", headers=headers)
    assert r.status_code == 200
    assert r.json()["agent"] == "wealth"
    assert r.json()["transcript"]


def test_list_summaries_filter(client: TestClient, headers) -> None:
    _seed_summary_via_api(client, headers, "risk")
    _seed_summary_via_api(client, headers, "wealth")
    r = client.get("/summaries?agent=risk", headers=headers)
    assert r.status_code == 200
    assert all(s["agent"] == "risk" for s in r.json())


def test_delete_summary(client: TestClient, headers) -> None:
    key = _seed_summary_via_api(client, headers)
    r = client.delete(f"/summaries/{key}", headers=headers)
    assert r.status_code == 204
    assert client.get(f"/summaries/{key}", headers=headers).status_code == 404


def test_prime_with_summary(client: TestClient, headers) -> None:
    key = _seed_summary_via_api(client, headers, "risk")
    sid = client.post("/agents/research/sessions", headers=headers).json()["session_id"]
    r = client.post(
        f"/agents/sessions/{sid}/prime",
        json={"summary_keys": [key]},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["reply"].startswith("echo:")


def test_prime_missing_keys_422(client: TestClient, headers) -> None:
    sid = client.post("/agents/risk/sessions", headers=headers).json()["session_id"]
    # Empty list violates the schema's min_length=1.
    r = client.post(
        f"/agents/sessions/{sid}/prime", json={"summary_keys": []}, headers=headers,
    )
    assert r.status_code == 422

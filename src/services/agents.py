"""Agent service: server-side chat sessions for the 5 conversational agents.

Slice 7 of the API refactor — see API_REFACTOR_PLAN.md §5.

Each session wraps an instance of one of the five agent classes
(``RiskAgent``, ``WealthAgent``, ``ResearchAgent``, ``PortfolioManagerAgent``,
``CIOAgent``). The agent itself maintains its multi-turn ``messages`` list;
the session cache stores the wrapping ``_AgentSession`` record by UUID.

Process-local cache: sessions are lost across uvicorn restarts. v2 will
add persistence (likely via the same ``agent_summaries.json`` store) so
that a chat can resume after a restart.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Dict

from src.agent import (
    CIOAgent,
    PortfolioManagerAgent,
    ResearchAgent,
    RiskAgent,
    WealthAgent,
)
from src.services.schemas.agent import (
    AgentKind,
    ChatHistory,
    ChatReply,
    ChatSession,
    ChatTurn,
)


# ── Agent registry ───────────────────────────────────────────────────────────

# Maps ``kind`` strings to the agent constructor. Public so tests can swap in
# stubs via ``register_agent_class`` rather than monkeypatching imports.
_AGENT_CLASSES: Dict[str, Callable[..., object]] = {
    "risk": RiskAgent,
    "wealth": WealthAgent,
    "research": ResearchAgent,
    "pm": PortfolioManagerAgent,
    "cio": CIOAgent,
}


def register_agent_class(kind: str, cls: Callable[..., object]) -> None:
    """Override or extend the agent registry (for tests + future agents)."""
    _AGENT_CLASSES[kind] = cls


def known_kinds() -> list[str]:
    return sorted(_AGENT_CLASSES.keys())


# ── Session cache ────────────────────────────────────────────────────────────


class _AgentSession:
    """One open chat session. Holds the agent instance and metadata."""

    __slots__ = ("session_id", "kind", "data_dir", "created_at", "_agent", "_lock")

    def __init__(self, session_id: str, kind: str, data_dir: str) -> None:
        self.session_id = session_id
        self.kind = kind
        self.data_dir = data_dir
        self.created_at = datetime.now(timezone.utc)
        self._agent: object | None = None
        self._lock = threading.Lock()

    def _ensure_agent_locked(self):
        """Lazy-init the wrapped agent. Caller MUST hold ``self._lock``.

        Anthropic client construction reads ``ANTHROPIC_API_KEY``; failures
        surface as an exception so the API returns a 500 with a clear
        ``detail`` instead of crashing the cache.
        """
        if self._agent is None:
            cls = _AGENT_CLASSES.get(self.kind)
            if cls is None:
                raise ValueError(f"Unknown agent kind: {self.kind!r}")
            self._agent = cls(data_dir=self.data_dir)
        return self._agent

    @contextmanager
    def locked(self):
        """Hold the session lock for the duration of one exchange.

        Use this around any code path that reads or mutates the wrapped
        agent's ``messages`` list — both ``chat_message`` and
        ``get_history`` go through here so chats serialise per-session
        and history snapshots don't race with mid-flight chats.

        Lazy-inits the agent on first acquisition.
        """
        with self._lock:
            yield self._ensure_agent_locked()

    @property
    def message_count(self) -> int:
        if self._agent is None:
            return 0
        return len(getattr(self._agent, "messages", []))


_sessions: Dict[str, _AgentSession] = {}
_sessions_lock = threading.Lock()


def _new_session_id() -> str:
    return uuid.uuid4().hex


def _get_session(session_id: str) -> _AgentSession:
    with _sessions_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise ValueError(f"Session {session_id!r} not found.")
    return session


def reset_sessions() -> None:
    """Clear the cache. Tests call this between cases."""
    with _sessions_lock:
        _sessions.clear()


# ── Public service surface ───────────────────────────────────────────────────


def start_chat(kind: str, data_dir: str) -> ChatSession:
    """Open a new chat session for ``kind``.

    The agent is created **lazily** on the first message — so a missing
    ``ANTHROPIC_API_KEY`` doesn't break session creation, only the first
    actual exchange.

    Raises:
        ValueError: ``kind`` not registered.
    """
    if kind not in _AGENT_CLASSES:
        raise ValueError(f"Unknown agent kind: {kind!r}. Known: {known_kinds()}")
    session_id = _new_session_id()
    session = _AgentSession(session_id, kind, data_dir)
    with _sessions_lock:
        _sessions[session_id] = session
    return _session_to_schema(session)


def chat_message(session_id: str, message: str) -> ChatReply:
    """Send one user message, return the agent's reply text.

    Serialised per session via ``_AgentSession.locked()`` so concurrent
    chats on the same session don't interleave on the agent's
    ``messages`` list. Different sessions still run in parallel.
    """
    if not (message or "").strip():
        raise ValueError("Message is empty.")
    session = _get_session(session_id)
    with session.locked() as agent:
        reply = agent.chat(message)  # type: ignore[attr-defined]
        msg_count = len(getattr(agent, "messages", []))
    return ChatReply(
        session_id=session.session_id,
        reply=reply,
        message_count=msg_count,
    )


def prime_chat(session_id: str, summary_keys: list[str]) -> ChatReply:
    """Prime an open session with one or more saved summaries.

    Pulls the entries from ``agent_summaries.json``, builds a single
    priming message via ``build_context_prompt``, and sends it through
    the agent as a user message. Returns the acknowledgement.

    Holds **no** session lock outside the inner ``chat_message`` call —
    safe to interleave with other operations on the same session, though
    in practice clients keep priming and chat sequential.

    Raises:
        ValueError: session unknown, no keys, or one or more keys missing.
    """
    if not summary_keys:
        raise ValueError("No summary keys provided.")
    from src import agent_summaries
    session = _get_session(session_id)
    entries = []
    missing: list[str] = []
    for key in summary_keys:
        entry = agent_summaries.get_summary(key, data_dir=session.data_dir)
        if entry is None:
            missing.append(key)
        else:
            entries.append(entry)
    if missing:
        raise ValueError(f"Unknown summary keys: {missing!r}")
    primer = agent_summaries.build_context_prompt(entries)
    return chat_message(session_id, primer)


def end_chat(session_id: str) -> None:
    """Drop a session from the cache. Idempotent: missing IDs raise 404."""
    with _sessions_lock:
        if session_id not in _sessions:
            raise ValueError(f"Session {session_id!r} not found.")
        del _sessions[session_id]


def get_session(session_id: str) -> ChatSession:
    """Metadata for one session."""
    return _session_to_schema(_get_session(session_id))


def get_history(session_id: str) -> ChatHistory:
    """Full transcript for a session — for clients re-rendering UI state.

    Snapshots ``messages`` under the session lock so iteration doesn't
    race with a concurrent ``chat_message`` mutating the list. Conversion
    to wire turns happens outside the lock.
    """
    session = _get_session(session_id)
    # Fast path: agent never instantiated → no history yet. Safe to read
    # without the lock — the agent only becomes non-None inside the lock,
    # so the worst we'd do is miss a brand-new agent's empty list, which
    # is what we'd return anyway.
    if session._agent is None:
        return ChatHistory(session_id=session.session_id, kind=session.kind, messages=[])
    with session._lock:
        raw = list(getattr(session._agent, "messages", []))
    turns: list[ChatTurn] = []
    for m in raw:
        role = m.get("role", "assistant")
        content = m.get("content", "")
        if isinstance(content, list):  # Anthropic content blocks list
            text = "".join(
                getattr(b, "text", "") if not isinstance(b, dict) else b.get("text", "")
                for b in content
            )
            content = text
        turns.append(ChatTurn(role=role, content=str(content)))
    return ChatHistory(session_id=session.session_id, kind=session.kind, messages=turns)


# ── Helpers used by services.summaries ───────────────────────────────────────


def _session_to_schema(session: _AgentSession) -> ChatSession:
    return ChatSession(
        session_id=session.session_id,
        kind=session.kind,  # type: ignore[arg-type]
        data_dir=session.data_dir,
        created_at=session.created_at,
        message_count=session.message_count,
    )


def _session_messages(session_id: str) -> tuple[str, str, list[dict]]:
    """Return ``(agent_kind, data_dir, messages)`` for a live session.

    Internal accessor used by ``services.summaries`` when saving — keeps
    callers out of the private session shape. Snapshots the message list
    under the session lock.
    """
    session = _get_session(session_id)
    with session.locked() as agent:
        return session.kind, session.data_dir, list(getattr(agent, "messages", []))


def _session_client(session_id: str):
    """The underlying ``anthropic.Anthropic`` client for a live session.

    ``summarize_conversation`` uses it to avoid a second client instantiation.
    """
    session = _get_session(session_id)
    with session.locked() as agent:
        return getattr(agent, "client", None)


__all__ = [
    "AgentKind",
    "start_chat",
    "chat_message",
    "prime_chat",
    "end_chat",
    "get_session",
    "get_history",
    "register_agent_class",
    "known_kinds",
    "reset_sessions",
]

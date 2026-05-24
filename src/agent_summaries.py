"""Persistent summaries of agent conversations.

A small JSON store under `data/agent_summaries.json` (per-data-dir, so demo
and live mode have separate sets). Each entry is keyed by
`"{agent}__{iso_datetime}"` and carries the agent name, started_at timestamp,
a Claude-generated natural-language summary, the message count, and the full
transcript for later audit / replay.

Designed for two flows:

  1. After a chat, click **💾 Save summary** in the dashboard → we ask Claude
     Haiku to compress the conversation into a few hundred chars and write it.
  2. When starting a new chat, pick one or more saved summaries to **load as
     context** — the priming text is appended as the first user message so the
     live agent sees the prior reasoning before answering anything new.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

import anthropic


SUMMARIES_FILENAME = "agent_summaries.json"

# Cheap + fast model for summarisation. Keeps the main agent (Opus) free for
# real work; Haiku is plenty for compressing a conversation into bullet points.
SUMMARY_MODEL = "claude-haiku-4-5-20251001"


# ── Storage ───────────────────────────────────────────────────────────────────

def _path(data_dir: str = "data") -> str:
    return os.path.join(data_dir, SUMMARIES_FILENAME)


def _read(data_dir: str = "data") -> dict:
    p = _path(data_dir)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write(d: dict, data_dir: str = "data") -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(_path(data_dir), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, default=str)


def make_key(agent: str, when: datetime) -> str:
    return f"{agent}__{when.isoformat(timespec='seconds')}"


# ── Summarisation ─────────────────────────────────────────────────────────────

def summarize_conversation(
    messages: list[dict],
    agent: str,
    *,
    client: Optional[anthropic.Anthropic] = None,
    max_chars: int = 1200,
) -> str:
    """Call Claude Haiku to compress a conversation into a concise summary.

    The summary aims to be useful as **future context** for a new agent run,
    so it prioritises: (1) what the user asked, (2) concrete numbers /
    findings, (3) recommendations or conclusions.
    """
    if not messages:
        return "(empty conversation)"

    transcript = "\n\n".join(
        f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
        for m in messages
    )

    if client is None:
        client = anthropic.Anthropic()

    resp = client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                f"Summarize this conversation with the **{agent}** agent in "
                f"under {max_chars} characters. Capture:\n"
                "  1. What the user asked / wanted to know.\n"
                "  2. Concrete numbers, tickers, or facts the agent surfaced.\n"
                "  3. Any specific recommendations or conclusions.\n\n"
                "Be terse and concrete. Skip pleasantries. This summary will "
                "be used to reload context into future agent conversations, so "
                "favour information density over readability.\n\n"
                f"--- CONVERSATION ---\n{transcript}"
            ),
        }],
    )
    out_parts = [b.text for b in resp.content if hasattr(b, "text")]
    return "\n".join(out_parts).strip() or "(no summary generated)"


# ── Save / load / list / delete ──────────────────────────────────────────────

def save_summary(
    agent: str,
    messages: list[dict],
    summary: Optional[str] = None,
    *,
    client: Optional[anthropic.Anthropic] = None,
    data_dir: str = "data",
) -> tuple[str, dict]:
    """Persist a summary. Returns (key, full_entry)."""
    if not messages:
        raise ValueError("Cannot save an empty conversation.")
    if summary is None:
        summary = summarize_conversation(messages, agent, client=client)
    when = datetime.now()
    key = make_key(agent, when)
    entry = {
        "agent":         agent,
        "started_at":    when.isoformat(timespec="seconds"),
        "summary":       summary,
        "message_count": len(messages),
        "transcript":    messages,
    }
    store = _read(data_dir)
    store[key] = entry
    _write(store, data_dir)
    return key, entry


def list_summaries(
    data_dir: str = "data",
    agent: Optional[str] = None,
) -> list[dict]:
    """Return all summaries as a list, newest first.
    Each item: {key, agent, started_at, summary, message_count, transcript}."""
    items = [
        {"key": k, **v}
        for k, v in _read(data_dir).items()
    ]
    if agent is not None:
        items = [s for s in items if s.get("agent") == agent]
    items.sort(key=lambda s: s.get("started_at", ""), reverse=True)
    return items


def get_summary(key: str, data_dir: str = "data") -> Optional[dict]:
    return _read(data_dir).get(key)


def delete_summary(key: str, data_dir: str = "data") -> bool:
    store = _read(data_dir)
    if key in store:
        del store[key]
        _write(store, data_dir)
        return True
    return False


# ── Context priming ──────────────────────────────────────────────────────────

def build_context_prompt(summary_entries: list[dict]) -> str:
    """Format one-or-more saved summaries into a single priming message that
    can be prepended to a new agent conversation."""
    if not summary_entries:
        return ""
    parts = [
        "I'm including context from past conversations so you can reference "
        "them in your reasoning. **Acknowledge briefly that you've read them, "
        "then wait for my next question — don't re-analyse anything yet.**\n"
    ]
    for s in summary_entries:
        parts.append(
            f"\n--- Past conversation with the {s.get('agent', 'unknown')} agent "
            f"on {s.get('started_at', '')} "
            f"({s.get('message_count', 0)} messages) ---\n"
            f"{s.get('summary', '')}"
        )
    return "\n".join(parts)

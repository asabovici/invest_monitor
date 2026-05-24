# Conversation Summaries

Save and re-load summaries of past agent conversations so you can carry context across sessions.

The classic workflow: chat with the **Risk Agent** today about your portfolio's VaR under a 2008 scenario; tomorrow, start a fresh chat with the **Wealth Agent** and pull in yesterday's summary as priming context. The wealth agent now knows what the risk agent already established without you having to re-explain.

## Saving a summary

Each agent chat tab on the Multi-Portfolio Dashboard has a **💾 Save summary** button next to **Clear conversation**. Click it after any non-trivial exchange and:

1. Claude **Haiku 4.5** is invoked to compress the conversation into a few hundred characters of structured text — what you asked, the concrete numbers / tickers the agent surfaced, and any specific recommendations.
2. The summary + full transcript + agent name + timestamp lands in `data/agent_summaries.json`, keyed on `"{agent}__{iso_datetime}"`.
3. A preview is shown so you can confirm before moving on.

Why Haiku? It's an order of magnitude cheaper than Opus for what is essentially a fixed-form summarisation task; the main agent stays on Opus for actual reasoning.

## Loading past context

Above the chat history of every agent tab there's a **📂 Load past conversation context (N saved)** expander when you have at least one summary stored. It's cross-agent: from inside the Risk chat you can load a past Wealth summary, etc.

1. Pick one or more saved summaries from the multiselect (they're sorted newest first and labelled with agent / timestamp / message count / preview).
2. Click **Load context**.
3. The selected summaries are concatenated into a single priming user message (template in `build_context_prompt`), sent to the agent. The agent reads them and acknowledges briefly, then waits for your real question.
4. The chat history shows a small "_📂 Loaded context from N past conversation(s)_" marker plus the agent's ack — you can then ask follow-ups that reference the prior context.

The priming template explicitly asks the agent to *acknowledge and wait*, not re-analyse, so the load round-trip stays cheap.

## Storage

| Path | Format |
|---|---|
| `data/agent_summaries.json` | Single JSON file. Top-level is `{key: entry}`. Auto-created on first save. |
| `data_demo/agent_summaries.json` | Demo mode's separate store. |

Each entry:

```json
{
  "agent": "risk",
  "started_at": "2026-05-17T14:30:00",
  "summary": "User asked about VaR. Risk: 95% 1d VaR -1.42% ($6.2k). Under 2008: -30%, Financials+Tech driven.",
  "message_count": 4,
  "transcript": [
    {"role": "user",      "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

The full transcript is kept alongside the summary so you can audit later or re-summarise with a different model.

## CLI

```bash
invest-monitor summaries list                          # newest first, all agents
invest-monitor summaries list --agent risk             # filter to one agent
invest-monitor summaries show "risk__2026-05-17T14:30:00"
invest-monitor summaries delete "risk__2026-05-17T14:30:00"
```

## Python API

```python
from src import agent_summaries

# Save (optionally provide your own summary string; otherwise Haiku is called)
key, entry = agent_summaries.save_summary(
    agent="wealth",
    messages=[{"role": "user", "content": "..."}, ...],
    # summary="...",  # optional — auto-generated if omitted
)

# Browse
agent_summaries.list_summaries()                       # all, newest first
agent_summaries.list_summaries(agent="risk")           # filter

# Fetch / delete
agent_summaries.get_summary(key)
agent_summaries.delete_summary(key)

# Build a priming prompt for an upcoming chat
entries = [agent_summaries.get_summary(k) for k in selected_keys]
primer = agent_summaries.build_context_prompt(entries)
```

## When to save

Save liberally — the on-disk cost is tiny (a few KB per summary) and the upside is being able to thread context across sessions weeks apart. A good rule of thumb: any conversation where the agent ran a tool (e.g. VaR computation, scenario stress, allocation suggestion) is worth saving so you can recall the numbers later.

If you find the list getting cluttered, the CLI `delete` command is the quickest way to prune. The Streamlit UI doesn't expose a delete button directly — keeps the chat tabs focused on chatting.

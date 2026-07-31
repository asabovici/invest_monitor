# Conversational agents

Six Claude-powered agents that share one architectural pattern. Each is a
single-actor tool-runner with multi-turn history. They are **not** the
LangGraph multi-agent coordination system (see `src/trading_graph/`) —
the PM and CIO classes here are the human-facing chat counterparts to
those graph nodes.

## Agents

| File | Class | CLI | Role |
|---|---|---|---|
| `agent.py` | `RiskAgent` | `invest-monitor agent` | Volatility, VaR, concentration, drawdown, stress |
| `wealth_agent.py` | `WealthAgent` | `invest-monitor wealth` | P&L, rebalance, goal MC, tax-loss, scenarios |
| `research_agent.py` | `ResearchAgent` | `invest-monitor research` | Web search + portfolio simulation for capital deployment |
| `portfolio_manager_agent.py` | `PortfolioManagerAgent` | `invest-monitor pm` | Build defensible trade proposals |
| `cio_agent.py` | `CIOAgent` | `invest-monitor cio` | Approve / override / kick back proposals |
| `data_agent.py` | `DataAgent` | `invest-monitor data` | **Writes.** Correct positions, security master, prices, fund holdings |

All six are exported from `src/agent/__init__.py`.

- **CLI** (`invest-monitor agent`, `wealth`, `research`, `pm`, `cio`, `data`)
  instantiates the agent class directly and drives a `run_interactive()`
  REPL. Stays direct because the input()-loop doesn't benefit from HTTP
  indirection.
- **Streamlit dashboard** and **future frontends** go through
  `src/services/agents.py`, which holds a process-local
  `{session_id: _AgentSession}` cache. Agents are instantiated lazily on
  the first message so a missing `ANTHROPIC_API_KEY` only breaks the
  first exchange, not session creation.
- **HTTP**: `/agents/{kind}/sessions`, `/agents/sessions/{id}/messages`,
  `/agents/sessions/{id}/prime`, `/agents/sessions/{id}/history`.
  Sessions don't survive uvicorn restarts — use `/summaries` for
  persistent context.

## The data agent is the only one that mutates

The other five read and reason. `DataAgent` changes stored records, so its
skills are built on a preview/apply gate in `src/services/datafix.py`: every
mutating skill returns a rendered diff plus a `change_id` and writes nothing;
only `apply_change` commits, taking a backup into `<data_dir>/.backups/<stamp>/`
and appending to `<data_dir>/audit_log.jsonl`. Three things worth knowing:

- **Retroactive position fixes go through the trade ledger.** Positions carry
  no time dimension, so the agent corrects a dated trade and replays the
  ledger. `_replay_ledger` must stay in lockstep with
  `Database._apply_trade_to_positions` or a replay silently rewrites correct
  data — `test_replay_of_untouched_ledger_is_a_noop` pins this.
- **Replay only governs tickers the ledger covers.** Positions imported from a
  CSV have no trades behind them; a naive replay would delete every one.
  `_merge_untracked` leaves them alone; a ledger-covered ticker that sells to
  zero is still removed.
- **Staged changes are process-local and single-use.** Same convention as the
  other session caches — `datafix.reset_staged()` for tests. An applied change
  is dropped so one approval can't be replayed.

## The pattern

```python
class XAgent:
    def __init__(self, data_dir: str = "data"):
        self.client = anthropic.Anthropic()                # ANTHROPIC_API_KEY env
        self.db = Database(data_dir)
        self.engine = ReportingEngine(self.db)
        self.tools = create_x_skills(self.db, self.engine) # @beta_tool list
        self.messages: list = []                           # multi-turn history

    def chat(self, user_input: str) -> str:
        ...beta tool runner loop...
```

- **Model**: `claude-opus-4-6` with `thinking={"type": "adaptive"}`. Don't
  change without coordinating across all 6 agents.
- **Tool runner**: `client.beta.messages.tool_runner(...)` auto-loops on
  tool calls until the model returns a final text block.
- **History**: only the final assistant text is appended, never
  thinking-block content, to avoid downstream `tool_runner` rejection.
- **Skills factory** lives in a sibling file `*_skills.py`. Returns a list
  of `@beta_tool`-decorated closures that capture `db` and `engine`.

## Skills (one module per agent)

| Module | Count | Purpose |
|---|---|---|
| `skills.py` | 13 | Risk analytics |
| `wealth_skills.py` | 12 | Wealth + MC + tax (includes `export_report`) |
| `research_skills.py` | 5 + `web_search_20260209` | Capital deployment |
| `pm_skills.py` | 7 | Trade proposals (includes `export_report`) |
| `cio_skills.py` | 7 | Holistic oversight (includes `export_report`) |
| `data_skills.py` | 16 | Data correction — all mutations behind a preview/apply gate |

`report_export.py` is the shared `export_report(filename, markdown_content,
overwrite=False)` skill — Wealth / PM / CIO all get it via
`make_export_report_skill(db, agent_kind=...)`. Files land in
`<data_dir>/reports/`, sanitised filename, 1 MB cap.

## Gotchas

- **Compare `AssetType` on `.value`, not the enum member.** Streamlit
  hot-reload re-imports `src.models` as a new module, giving you two
  distinct `AssetType` classes. `pos.asset.asset_type in (AssetType.ETF,)`
  silently fails after reload. Always use `.value in {"ETF", "Fund"}`.
- **Conversation summaries** (`src/agent_summaries.py`) compress chats via
  Haiku and persist to `<data_dir>/agent_summaries.json`. Keyed on agent
  name (`risk`, `wealth`, `research`, `pm`, `cio`, `data`) — adding a new agent
  just adds another key, no migration needed. The service wrapper at
  `src/services/summaries.py` is what clients should call; it reuses the
  session's own Anthropic client to avoid a second instantiation.
- **Web search** is server-side only (`{"type": "web_search_20260209"}`),
  resolved by Anthropic before the response reaches the tool runner.
  Composes cleanly with `@beta_tool` skills.

## Adding a new agent

1. New `XAgent` class mirroring the existing pattern.
2. `x_skills.py` with `create_x_skills(db, engine)` factory.
3. Append the shared `export_report` skill if it makes sense for this agent.
4. Export from `__init__.py`.
5. Register with the chat-session service:
   `src/services/agents.py:_AGENT_CLASSES["x"] = XAgent`.
6. Wire CLI in `src/cli.py` (copy an existing `agent`/`wealth`/`cio` command).
7. Add a dashboard tab in `src/app.py` (`_render_agent_chat("x", "X")`).
8. Update `AgentKind` Literal in `src/services/schemas/agent.py` if you
   want HTTP clients to be able to start sessions for it.
9. Document in `AGENTS.md` and `docs/ai-agents.md`.

## Future: bridging to the LangGraph

The PM / CIO classes here are intentionally close to the
`portfolio_manager` and `cio` nodes in `src/trading_graph/`. The plan is
for those nodes to delegate to these classes once real prompts replace
the deterministic stubs — see `API_REFACTOR_PLAN.md` and the spec.

# Trading graph — LangGraph multi-agent coordination

Four agent nodes — Researcher, Portfolio Manager, Risk Manager, CIO —
coordinated by a `StateGraph` around a shared `TradingState`. Agents
never call each other directly; the graph routes control. Persisted via
a `MemorySaver` checkpointer so runs can be paused (HITL) and resumed.

The spec lives at `SPEC_multi_agent_trading_system.md` (top-level) and a
user-facing description at `docs/multi-agent-graph.md`.

## Layout

```
src/trading_graph/
├── __init__.py        # Exports TradingState, initial_state, Settings, build_graph
├── state.py           # TradingState TypedDict + reducers + initial_state()
├── config.py          # Settings dataclass (model_name, HITL, max_revisions, thresholds)
├── routing.py         # route_after_risk, route_after_cio (with loop guard)
├── graph.py           # build_graph() — wires nodes + checkpointer + interrupt
├── run.py             # CLI smoke runner (`python -m src.trading_graph.run`)
└── nodes/
    ├── researcher.py          # Stub: produces market_signal + whitelist
    ├── portfolio_manager.py   # Stub: produces proposed_trades; increments revision_count
    ├── risk_manager.py        # Stub: concentration check using config.max_sector_concentration
    └── cio.py                 # Stub: signs off when risk_approved
```

## State contract

```python
class TradingState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]    # appends
    market_signal: dict | None
    whitelist: list[str]
    proposed_trades: dict | None
    risk_approved: bool
    risk_critique: Annotated[list[str], operator.add]       # appends
    final_execution_ready: bool
    revision_count: int
```

**Reducers matter.** `messages` and `risk_critique` **append** across
node updates — they're for accumulating context. Everything else is
last-write-wins.

## Flow

```
START → researcher → portfolio_manager → risk_manager
                       ↑                       │
                       │ (revision_count < max,│ approved
                       │  risk rejected)       ▼
                       │                      cio
                       │                       │ sign-off
                       │                       ▼
                       │                      END
                       │
                       │  (CIO requests follow-up research)
                       └────── researcher ◀────┘
```

Two loop guards:

- **PM ↔ Risk Manager** bounded by `Settings.max_revisions` (default 3).
  When `revision_count >= max_revisions` and `risk_approved=False`,
  routing exits to `__end__` instead of looping forever.
- **CIO follow-up** is also bounded by `max_revisions` in practice
  (since each follow-up adds a revision when PM is re-invoked).

## Configuration

`config.Settings` is a frozen dataclass — all thresholds and model
choices flow from here. **Never hardcode them inside a node.**

| Setting | Default | Purpose |
|---|---|---|
| `model_name` | `"claude-sonnet-4-20250514"` | LLM used when prompts replace stubs |
| `human_in_the_loop` | `True` | Interrupt before `cio` for sign-off |
| `max_revisions` | `3` | Caps the PM↔Risk loop |
| `var_limit` | `0.05` | Risk Manager VaR cap |
| `max_sector_concentration` | `0.30` | Risk Manager per-position weight cap |

## Running a graph

```python
from src.trading_graph import Settings, build_graph, initial_state

app = build_graph(Settings(human_in_the_loop=False))
config = {"configurable": {"thread_id": "run-1"}}
final = app.invoke(initial_state(), config=config)
assert final["final_execution_ready"]
```

With HITL the first `invoke` pauses before `cio`; resume by invoking
with `None` on the same `thread_id`. The `MemorySaver` keeps state
between the two calls.

## Stubs vs real prompts

All four node files currently return deterministic placeholder values
(see the spec's §9 step 8). The graph is fully testable today without
LLM calls. Replacing stubs with real `client.messages.create(...)` calls
should keep the same return-key shape so the existing tests pass.

The conversational PM / CIO agents at `src/agent/portfolio_manager_agent.py`
and `cio_agent.py` are the human-facing counterparts; the long-term plan
is for the graph nodes to delegate to those classes once real prompts
land.

## Tests

`tests/test_trading_graph_state.py` (reducer semantics),
`tests/test_trading_graph_routing.py` (every branch, including loop
guard), and `tests/test_trading_graph_smoke.py` (end-to-end termination
and HITL pause-then-resume). All 15 tests run without an
`ANTHROPIC_API_KEY`.

## Common pitfalls

- **Don't write to `messages` or `risk_critique` with `[overwrite_value]`**
  — that's not how the reducers compose. Return the *new entries only*;
  LangGraph appends them.
- **Always pass `config={"configurable": {"thread_id": ...}}`** when
  invoking the compiled graph. The checkpointer is keyed on thread_id;
  without one you'll get a runtime error.
- **`interrupt_before=["cio"]`** only fires when HITL is on. The
  routing function still returns `"cio"` either way; the interrupt is a
  separate concern.

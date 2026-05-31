# API Refactor Plan

> Goal: Reorganise invest-monitor so all business logic sits behind a typed
> service layer exposed over HTTP. The Streamlit dashboard keeps working
> throughout. Once the API is stable, a React / Vue / mobile / CLI client
> can be dropped in by talking to the same endpoints.

## 1. Target architecture

```
┌────────────────────────────────────────────────────────────┐
│  Clients                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────┐ │
│  │ Streamlit (now)  │  │  Click CLI       │  │  React?  │ │
│  └────────┬─────────┘  └────────┬─────────┘  └────┬─────┘ │
└───────────┼─────────────────────┼─────────────────┼───────┘
            │  (in-process)       │ (HTTP)          │ (HTTP)
            ▼                     ▼                 ▼
   ┌──────────────────────────────────────────────────────┐
   │  FastAPI app  (src/api/)                             │
   │   - routers/  one file per resource (portfolios,     │
   │               prices, reports, agents, scenarios, …) │
   │   - schemas/  pydantic request/response models       │
   │   - deps.py   shared deps (data_dir, db, settings)   │
   └──────────────────────┬───────────────────────────────┘
                          │ (function calls — no HTTP overhead)
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │  Service layer  (src/services/)                      │
   │   - portfolios.py   list, get, create, delete, …     │
   │   - prices.py       fetch, latest, history, …        │
   │   - reports.py      risk, exposure, attribution, …   │
   │   - scenarios.py    stress test, MC, regime, …       │
   │   - agents.py       chat (PM/CIO/…), summaries, …    │
   │   - groups.py       portfolio groups CRUD            │
   │   - production.py   job runner controls              │
   │   Each function: typed args, returns dataclasses     │
   │   /pydantic models. No Streamlit, no Click, no HTTP. │
   └──────────────────────┬───────────────────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │  Domain / data layer  (existing, unchanged in v1)    │
   │  Database, ReportingEngine, AttributionEngine,       │
   │  Collector, agent_summaries, scenarios, benchmarks,  │
   │  Agent classes, trading_graph                         │
   └──────────────────────────────────────────────────────┘
```

**Key invariants**

1. **Service layer never imports Streamlit, Click, or FastAPI.** It's a
   pure-Python package.
2. **Streamlit and Click both call into the service layer** — never
   directly into Database/ReportingEngine in code we touch in this
   refactor. (Existing direct calls in `src/app.py` get migrated
   incrementally; see §5.)
3. **FastAPI is the only place that knows about HTTP.** Routers are
   thin: parse request → call service → wrap response.
4. **Agent runs stay server-side.** API exposes `POST /agents/{kind}/chat`
   etc. so `ANTHROPIC_API_KEY` never leaves the server. Conversation
   state is still in-process for now (see §7 — open questions).

## 2. Module layout

```
src/
├── api/                       ← NEW: FastAPI app
│   ├── __init__.py
│   ├── main.py                ← `app = FastAPI(...)`, mounts routers
│   ├── deps.py                ← dep-injection: data_dir, Settings, Database
│   ├── routers/
│   │   ├── portfolios.py      ← /portfolios
│   │   ├── prices.py          ← /prices
│   │   ├── reports.py         ← /reports/{kind}
│   │   ├── scenarios.py       ← /scenarios
│   │   ├── benchmarks.py      ← /benchmarks
│   │   ├── groups.py          ← /groups
│   │   ├── trades.py          ← /trades
│   │   ├── agents.py          ← /agents/{kind}/chat, /summaries
│   │   ├── trading_graph.py   ← /trading-graph/run, /trading-graph/resume
│   │   └── production.py      ← /production/jobs, /production/runs
│   └── schemas/               ← pydantic models, one file per resource
│       ├── portfolio.py
│       ├── price.py
│       ├── report.py
│       ├── ...
│       └── common.py          ← shared error/pagination shapes
│
├── services/                  ← NEW: typed pure-Python service layer
│   ├── __init__.py
│   ├── _types.py              ← shared dataclasses/typed-dicts
│   ├── portfolios.py
│   ├── prices.py
│   ├── reports.py
│   ├── scenarios.py
│   ├── benchmarks.py
│   ├── groups.py
│   ├── trades.py
│   ├── agents.py
│   ├── trading_graph.py
│   └── production.py
│
├── app.py                     ← unchanged behaviour; migrates to call
│                                  services/ instead of Database directly
├── cli.py                     ← migrates similarly
├── agent/                     ← unchanged; classes are wrapped by
│                                  services.agents but not rewritten
├── trading_graph/             ← unchanged
├── database/, reporting.py,   ← unchanged data/domain layer
│   attribution.py, collector.py, scenarios.py, benchmarks.py,
│   agent_summaries.py, production.py, scheduler.py
```

## 3. Service-layer surface (first pass)

These are functions, not endpoints — the API just reflects them.
Signatures are illustrative; final types live in `src/services/_types.py`
and `src/api/schemas/`.

### portfolios.py
- `list_portfolios(data_dir) -> list[PortfolioSummary]`
- `get_portfolio(data_dir, name) -> PortfolioDetail`
- `create_portfolio(data_dir, name) -> PortfolioDetail`
- `delete_portfolio(data_dir, name) -> None`
- `load_portfolio_from_csv(data_dir, csv_bytes, name) -> PortfolioDetail`
- `update_positions(data_dir, name, positions: list[PositionInput]) -> PortfolioDetail`

### prices.py
- `collect_prices(data_dir, portfolio_name: str | None, period: str) -> CollectionResult`
- `get_latest_prices(data_dir, tickers) -> dict[str, float]`
- `get_historical_prices(data_dir, tickers, start: date | None) -> PriceHistory`

### reports.py
- `risk_metrics(data_dir, portfolio_name) -> RiskMetricsReport`
- `exposure(data_dir, portfolio_name, lookthrough: bool) -> ExposureReport`
- `income_projection(data_dir, portfolio_name) -> IncomeReport`
- `attribution(data_dir, portfolio_name, start, end) -> AttributionReport`
- `correlation_matrix(data_dir, portfolio_name) -> CorrelationReport`

### scenarios.py
- `list_scenarios() -> list[ScenarioInfo]`
- `run_stress(data_dir, portfolio_name, scenario_id, custom_shocks: dict | None) -> StressResult`
- `run_monte_carlo(data_dir, portfolio_name, scenario_id, horizon_days, sims, ...) -> MCResult`
- `wealth_projection(data_dir, portfolio_name, ...) -> WealthProjection`

### benchmarks.py
- `list_benchmarks() -> list[BenchmarkInfo]`
- `benchmark_returns(data_dir, benchmark_id, start, end) -> ReturnsSeries`
- `compare_to_benchmark(data_dir, portfolio_name, benchmark_id, ...) -> ComparisonResult`

### groups.py
- `list_groups(data_dir) -> list[GroupInfo]`
- `create_group(data_dir, name, description) -> GroupInfo`
- `add_to_group / remove_from_group / delete_group / get_group`

### trades.py
- `list_trades(data_dir, portfolio_name)`
- `record_trade(data_dir, ...)`

### agents.py
- `start_chat(kind: AgentKind, data_dir) -> ChatSessionId`
- `chat_message(session_id, message) -> AgentReply`
- `end_chat(session_id) -> None`
- `list_summaries(data_dir, agent: str | None) -> list[SummaryInfo]`
- `save_summary(session_id) -> SummaryInfo`
- `get_summary / delete_summary`

### trading_graph.py
- `start_run(settings: TradingGraphSettings) -> RunId`
- `step_run(run_id, input) -> RunState`
- `resume_after_hitl(run_id, approval | override) -> RunState`
- `get_run_state(run_id) -> RunState`

### production.py
- `list_jobs(data_dir) -> list[JobStatus]`
- `run_job(data_dir, job_id) -> RunResult`
- `list_runs(data_dir, limit) -> list[RunRecord]`

## 4. HTTP endpoint map (mirrors §3)

| Method | Path | Service call |
|---|---|---|
| GET | `/portfolios` | `portfolios.list_portfolios` |
| POST | `/portfolios` | `portfolios.create_portfolio` |
| GET | `/portfolios/{name}` | `portfolios.get_portfolio` |
| DELETE | `/portfolios/{name}` | `portfolios.delete_portfolio` |
| POST | `/portfolios/{name}/load-csv` | `portfolios.load_portfolio_from_csv` |
| PUT | `/portfolios/{name}/positions` | `portfolios.update_positions` |
| GET | `/prices/latest?tickers=AAPL,MSFT` | `prices.get_latest_prices` |
| GET | `/prices/history?tickers=...&start=...` | `prices.get_historical_prices` |
| POST | `/prices/collect` | `prices.collect_prices` |
| GET | `/reports/{kind}/{portfolio}` | `reports.*` |
| GET | `/scenarios` | `scenarios.list_scenarios` |
| POST | `/scenarios/stress` | `scenarios.run_stress` |
| POST | `/scenarios/monte-carlo` | `scenarios.run_monte_carlo` |
| POST | `/scenarios/wealth-projection` | `scenarios.wealth_projection` |
| GET | `/benchmarks` | `benchmarks.list_benchmarks` |
| GET | `/benchmarks/{id}/returns` | `benchmarks.benchmark_returns` |
| GET | `/groups` | `groups.list_groups` |
| POST | `/groups` | `groups.create_group` |
| ... | trades, summaries, production endpoints follow same pattern |
| POST | `/agents/{kind}/sessions` | `agents.start_chat` |
| POST | `/agents/{kind}/sessions/{id}/messages` | `agents.chat_message` (streams? see §7) |
| DELETE | `/agents/{kind}/sessions/{id}` | `agents.end_chat` |
| POST | `/trading-graph/runs` | `trading_graph.start_run` |
| GET | `/trading-graph/runs/{id}` | `trading_graph.get_run_state` |
| POST | `/trading-graph/runs/{id}/resume` | `trading_graph.resume_after_hitl` |

All responses are JSON. DataFrames are serialised as
`{"columns": [...], "rows": [[...]]}` via a shared helper.

## 5. Migration sequence

One PR-sized commit per step. Each step keeps Streamlit + CLI green.

1. **Scaffold** `src/services/` and `src/api/`. Empty modules + tests
   skeleton. FastAPI app boots and `/health` returns `{"status": "ok"}`.
2. **Add FastAPI deps** (`fastapi`, `uvicorn`, `httpx` for tests) and a
   `make_api` / `uv run invest-monitor serve` CLI command.
3. **Slice 1 — portfolios** (read paths). Implement
   `services/portfolios.py` for `list_portfolios` and `get_portfolio`.
   Add API routes. Migrate `src/app.py` + the CLI's `portfolio list` /
   `portfolio show` to call the service.
4. **Slice 2 — portfolios mutations.** create / delete / load-csv /
   update-positions. Same shape.
5. **Slice 3 — prices.** collect, latest, history. Migrate the
   collector-dependent calls in Streamlit (`_fetch_prices_cached` etc.)
   to use the service.
6. **Slice 4 — reports.** risk, exposure, income, attribution,
   correlation. This unblocks most of the Streamlit dashboard tabs.
7. **Slice 5 — scenarios & benchmarks.** Heavier compute paths;
   re-use the service from both Streamlit and CLI.
8. **Slice 6 — groups & trades.** Routine CRUD.
9. **Slice 7 — agents.** Sessions via FastAPI; existing Agent classes
   become per-session objects held in a server-side cache. Streamlit
   chat-tab code switches from instantiating `RiskAgent()` directly to
   calling the API in-process.
10. **Slice 8 — trading-graph.** Wrap `build_graph()` + checkpointer
    behind run/resume endpoints. HITL pause becomes a real REST step.
11. **Slice 9 — production / scheduler.** Job status, manual run-now,
    daemon controls.
12. **Cleanup.** Once nothing in `src/app.py` or `src/cli.py` calls
    `Database` / `ReportingEngine` / `AttributionEngine` directly, lock
    that with a lint rule.

Order rationale: read-only slices first (cheap to verify), then writes,
then long-running and streaming-flavoured pieces last.

## 6. Testing strategy

- **Service-layer tests** under `tests/services/test_*.py` — pure
  Python, no HTTP. Use the demo data dir (`data_demo/`) as fixture.
- **API-layer tests** under `tests/api/test_*.py` using FastAPI's
  `TestClient` (httpx-backed). Same coverage as the service tests but
  one layer up — verify request parsing, status codes, error shape.
- **Existing tests stay green** at every step. Trading-graph and
  report-export tests already pass and don't need to change.
- Add a smoke test that boots the FastAPI app and hits `/health`.

## 7. Open questions to confirm before/during build

| # | Question | Default |
|---|---|---|
| Q1 | Should the API run as a separate process, or can Streamlit talk to services in-process? | **Both supported**: Streamlit calls services directly; CLI's `serve` boots FastAPI for external clients. |
| Q2 | Auth? | **None in v1** (loopback only). Stub a header-based key check that's a no-op by default. **Gating item for non-localhost deployment** — see §11. |
| Q3 | Streaming agent responses (SSE/WebSocket)? | **Defer.** First version returns the full agent reply once the tool runner finishes. Open follow-up for streaming. |
| Q4 | Persistent agent sessions across server restarts? | **Defer.** v1 keeps sessions in an in-process dict. Already matches today's behaviour. |
| Q5 | DataFrame serialisation format? | **`{columns, rows}`** for JSON; future versions can negotiate Arrow over `application/vnd.apache.arrow.stream`. |
| Q6 | Active data dir (live vs demo) — query param, header, or session? | **Header** `X-Data-Dir: data` / `data_demo` with a server-side default. Mirrors today's sidebar toggle without baking it into URLs. |
| Q7 | OpenAPI / typed client generation? | FastAPI gives `/openapi.json` for free — leave it on, optionally generate a TS client later. |

## 8. Deliverables

- `src/api/`, `src/services/`, `tests/api/`, `tests/services/`
- `pyproject.toml` adds `fastapi`, `uvicorn`, `httpx[test]`
- New CLI command: `invest-monitor serve [--host --port --data-dir]`
- Updated docs: `docs/api.md` (endpoint reference auto-derived from OpenAPI),
  `docs/developer.md` codebase map, `docs/multi-agent-graph.md` updated
  to reference the new graph-run endpoints
- Updated `AGENTS.md` (agents via API rather than direct instantiation)

## 9. Non-goals

- Replacing Streamlit or building a new frontend. That's a separate
  project once this refactor lands.
- Auth, multi-tenancy, multi-user data isolation.
- Live-streaming agent tokens.
- Replacing parquet storage with a database server.
- Touching `data/` / `data_demo/` schemas. The parquet layer is unchanged.

## 10. Risk + mitigation

| Risk | Mitigation |
|---|---|
| 3470-line `src/app.py` is hard to migrate atomically | Per-slice incremental migration (§5); each slice is its own commit and leaves Streamlit fully working. |
| Agent session lifecycle (HITL pauses, summaries) is stateful | Server-side session cache keyed by UUID; `start_chat` returns the id, all subsequent calls pass it. Mirrors the Streamlit `session_state` model. |
| FastAPI dep adds startup cost / one more process | `serve` is opt-in via a CLI command; the package import path stays usable without it. |
| Hidden Streamlit-specific assumptions (caching via `@st.cache_*`) | Service layer is pure — caching moves to a service-level decorator using `functools.lru_cache` keyed on `(data_dir, …)`. |

## 11. Gating items before non-localhost deployment

The API is currently safe to run on `127.0.0.1` and only on `127.0.0.1`.
The items below MUST be resolved before binding to a non-loopback
interface, exposing through a reverse proxy, or running behind any kind
of authenticated tunnel.

### 11.1 Authentication / authorisation

- **State today:** every endpoint is anonymous. `POST /production/jobs/{name}/run`,
  `POST /production/metrics-refresh`, and the agent / trading-graph
  surfaces all execute privileged work for any caller.
- **Required:** at minimum, a bearer-token / API-key middleware. Optional
  per-route ACLs once the threat model is fleshed out.

### 11.2 `X-Data-Dir` path traversal

- **State today:** `src/api/deps.py:data_dir_dep` reads the header
  verbatim. Callers can point the server at any filesystem path the
  process can read and write — `/etc`, `/`, `/home/<user>/...`, etc.
- **Required:** clamp `data_dir` to a configured allowlist of directories
  (e.g. `{"data", "data_demo"}` resolved against the project root) and
  reject anything else with 400.
- **Defence in depth:** drop the env-var fallback in production-mode
  builds so the data dir can only come from a vetted set.

### 11.3 Long-running endpoints are DoS-shaped

- **State today:** `POST /prices/collect`, `POST /production/jobs/.../run`,
  and `POST /production/metrics-refresh` are synchronous and can hold a
  worker for minutes. An unauthenticated caller can trivially exhaust
  the worker pool.
- **Required:** rate limiting on those endpoints, or move them to a
  background-job queue with the HTTP surface limited to "enqueue" +
  "poll status". The background-jobs slice noted in API_REFACTOR_PLAN.md
  §7 Q3 covers this.

### 11.4 Session / run IDs are unguessable but unowned

- **State today:** `/agents/sessions/{id}` and `/trading-graph/runs/{id}`
  rely on UUID4 IDs. Any caller who knows the ID can read history,
  resume, or override state.
- **Required:** once auth lands, scope sessions and runs to the
  authenticated principal so an ID is necessary but not sufficient.

The body-size middleware already protects against trivial upload-based
DoS (capped at 10 MB, chunked uploads enforced by the receive-wrapper
branch — see `tests/api/test_middleware.py`). That part can ship as-is.

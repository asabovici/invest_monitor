# Service layer

Pure-Python typed functions that wrap the domain modules (`Database`,
`ReportingEngine`, `AttributionEngine`, `Collector`, `Benchmark`
catalogue, `JobRunner`, agent classes, trading graph). Every client —
Streamlit, the CLI, the FastAPI app, future frontends — calls into this
layer instead of touching the domain modules directly.

`__init__.py` is the canonical reference for the architectural rules.
This file lists the layout and the day-to-day conventions.

## Layout

```
src/services/
├── __init__.py        # Rules: invariants, ValueError phrasing, NaN convention
├── _db.py             # @lru_cache-backed _get_db(data_dir)
├── schemas/           # Canonical pydantic models (re-exported by src/api/schemas)
│   ├── agent.py
│   ├── benchmark.py
│   ├── group.py
│   ├── portfolio.py
│   ├── price.py
│   ├── production.py
│   ├── report.py
│   ├── scenario.py
│   ├── summary.py
│   ├── trade.py
│   └── trading_graph.py
├── portfolios.py      # list / get / create / delete / load-csv / update-positions
├── prices.py          # latest / history / collect (tickers list | portfolio | all)
├── reports.py         # risk / exposure / income / correlation / attribution + df helpers
├── scenarios.py       # catalogues + sector stress (+ df helper)
├── benchmarks.py      # catalogue + returns / stats / compare-to-portfolio
├── groups.py          # CRUD + memberships (atomic replace, rejects unknowns)
├── trades.py          # list / record_trade (ledger reads + writes)
├── agents.py          # chat sessions: start / message / prime / end + history
├── summaries.py       # list / get / delete / save_summary_from_session
├── trading_graph.py   # start_run / get_run_state / resume_run / end_run
├── datafix.py         # data correction: preview/apply gate, ledger replay, backups
├── dashboard.py       # aggregate snapshot: totals, breakdowns, weekly value series
├── exposure.py        # look-through by asset class + equity sector (fund profiles)
├── risk.py            # trailing risk metrics + Monte Carlo projection
├── income.py          # portfolio-wide income projection (delegates to reports.py)
└── production.py      # list_jobs / get / set_enabled / run / run_due / list_runs / refresh_metrics
```

## Invariants (enforced by tests)

1. **No imports from `streamlit`, `click`, `fastapi`, or `uvicorn`.**
   Pydantic and pandas are fine. The service layer is framework-free.
2. **Functions take primitives and return pydantic models / primitives.**
   No DataFrame in public signatures — convert via the `*_to_dataframe`
   helpers (`income_report_to_dataframe`, `price_history_to_dataframe`,
   `stress_result_to_dataframe`, `covariance_to_dataframe`,
   `correlation_to_dataframe`) for in-process callers that want pandas.
3. **All Database construction goes through `_get_db(data_dir)`**, never
   `Database(data_dir)` directly. The LRU cache is shared per process.
4. **Direct domain-class references in `src/app.py` and `src/cli.py`
   are capped** — see `tests/test_lint_domain_layering.py`. Each cleanup
   PR ratchets the cap down. New direct references fail the test.

## ValueError phrasing convention

The FastAPI layer's global handler in `src/api/errors.py` maps service
exceptions to HTTP statuses **by phrase**. When you raise:

| Phrase in the message | HTTP status |
|---|---|
| `"not found"` or `"does not exist"` | 404 |
| `"already exists"` | 409 |
| anything else | 400 |

Stick to these phrasings. If you need a different status code, change
the message — don't reach into the API layer. The service-layer tests
also assert on `match=` substrings, so phrasing is double-pinned.

## NaN / missing-data convention

Pandas/numpy intermediates often contain `NaN`. Pick one representation
per shape:

- **Matrices** (covariance, correlation, ticker × ticker dicts):
  `NaN` → `0.0`. Implemented in `reports._matrix_to_dict`.
- **Time series** (prices, daily returns, cumulative returns, benchmark
  overlays): `NaN` → `None`. Series stays aligned to the date index so
  callers can rebuild a DataFrame without re-aligning.

If you add a new endpoint, pick the side matching the data shape and
document it in the schema docstring.

## Session caches

Three services hold process-local state in module-level dicts. All three
expose a `reset_*()` helper that the autouse fixture in tests calls so
runs don't leak across cases.

| Service | Cache | Reset helper |
|---|---|---|
| `agents.py` | `_sessions: dict[session_id, _AgentSession]` | `reset_sessions()` |
| `trading_graph.py` | `_runs: dict[run_id, _RunRecord]` + `_get_compiled_graph` LRU | `reset_runs()` |
| `_db.py` | `_get_db.cache` | `reset_db_cache()` |
| `datafix.py` | `_staged: dict[change_id, _Staged]` | `reset_staged()` |

Sessions are lost across uvicorn restarts. v2 will add persistence (likely
via the same `agent_summaries.json` store for agent sessions).

## The one mutating-by-design service

`datafix.py` exists to correct existing records, so it does not follow the
usual "call it and it happens" shape. Every mutating entry point is a
`preview_*` function that computes a diff, stages it, and writes nothing;
`apply_change(change_id)` is the only thing that touches disk, and it backs up
each affected file to `<data_dir>/.backups/<stamp>/` and appends to
`<data_dir>/audit_log.jsonl` first. Changes are single-use.

Positions are corrected *through the trade ledger* (`preview_trade_correction`
/ `_insert` / `_delete`) rather than edited directly, because `positions.parquet`
has no time dimension and a direct edit would leave the ledger disagreeing.
`_replay_ledger` mirrors `Database._apply_trade_to_positions` exactly — if you
change one, change both, or replays will silently rewrite correct data.

## Aggregate screen endpoints

`dashboard.py`, `exposure.py`, `risk.py` and `income.py` each back exactly
one front-end screen and return everything it renders in a single call.
That is deliberate: composing them client-side meant one price-history
request per holding — dozens of round trips for a page load.

They compose rather than duplicate. `exposure`, `risk` and `income` all
call `dashboard.get_snapshot()` for priced holdings, and `income`
delegates the rate arithmetic to `reports.income_projection` because the
unit rules (dollars-per-share-per-payment for equities, annual percent for
cash-like) are easy to invert without the number looking wrong.

Two data realities they encode, both found against the live dataset:

- **`daily_portfolio_metrics` is not a net-worth series.** Coverage is
  ragged, so summing by date produces cliffs where an account has no row
  (an apparent -81% drop in one session). `dashboard.py` values current
  holdings at historical prices instead — a constant-holdings series, and
  labelled as such everywhere it surfaces.
- **Corrupted prices silently wreck risk.** A quote that collapses and
  returns days later is a bad tick, not a return; leaving them in put the
  fitted return at 35% a year. `risk.py` excludes moves that *round-trip*
  rather than moves that are merely large, so genuine tail events survive.

## Long-running endpoints

These are synchronous and can hold a worker for minutes — document any
new long-running additions:

- `services.prices.collect_prices` (yfinance per ticker)
- `services.production.run_job` for the four built-ins, especially
  `collect_prices` and `refresh_attribution`
- `services.production.refresh_metrics` (wraps
  `AttributionEngine.refresh_all`)

A streaming / background-job version is planned in a later slice.

## Deferred work (per `API_REFACTOR_PLAN.md`)

Some logic deliberately doesn't live here yet:

- ~~Monte Carlo wealth projection~~ — **done.** `services.risk.
  simulate_paths` is now the single simulation engine; the two hand-rolled
  copies in `src/agent/wealth_skills.py` were replaced with calls to it and
  the outputs verified byte-identical across eight cases, including
  multi-phase scenarios with one-time shocks. `tests/services/test_risk.py`
  fails if a hand-rolled `paths = np.zeros(...)` reappears.
- **Single-fund profile fetch + fund-holdings CSV upload** — Streamlit
  still calls `Collector.fetch_fund_profile` and `Ingester` directly.
  Both are UI-only flows with no service surface today.
- **`db.get_portfolio()` reads in `src/app.py`** — ~16 sites that hand a
  domain `Portfolio` to lookthrough / metrics / agent inputs. Need to be
  migrated alongside their consumers.
- **Ad-hoc `reporting.calculate_returns` chart panels** — 3 sites in
  `src/app.py`.

The ratchet test caps direct refs at the post-cleanup baseline; each new
service drops the cap.

## Tests

Mirror the module names — `tests/services/test_<module>.py` (logic) and
`tests/api/test_<module>.py` (HTTP semantics). The service tests use
`data_demo` for reads and `tmp_path` for mutations. `yfinance` is
monkeypatched on `sys.modules` for hermetic `collect_prices` tests.
`JOB_REGISTRY` is monkeypatched for production tests; `register_agent_class`
swaps in stub agent classes for chat-session tests.

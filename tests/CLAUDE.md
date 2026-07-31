# Tests

`pytest` discovers `tests/test_*.py` from the project root. Two subdirs
mirror the service-layer split, plus several top-level tests for older
modules and the layering ratchet.

## Layout

```
tests/
├── services/                          # Pure-Python service-layer logic
│   ├── test_agents.py
│   ├── test_benchmarks.py
│   ├── test_groups.py
│   ├── test_portfolios.py
│   ├── test_portfolios_mutations.py
│   ├── test_prices.py
│   ├── test_production.py
│   ├── test_reports.py
│   ├── test_scenarios.py
│   ├── test_summaries.py
│   ├── test_trades.py
│   └── test_trading_graph.py
├── api/                               # HTTP semantics via FastAPI TestClient
│   ├── test_agents.py
│   ├── test_benchmarks.py
│   ├── test_groups.py
│   ├── test_middleware.py
│   ├── test_portfolios.py
│   ├── test_portfolios_mutations.py
│   ├── test_prices.py
│   ├── test_production.py
│   ├── test_reports.py
│   ├── test_scenarios.py
│   ├── test_trades.py
│   └── test_trading_graph.py
├── test_database.py                   # Database parquet store (pre-refactor)
├── test_report_export.py              # Shared export_report skill
├── test_lint_domain_layering.py       # Ratchet: caps direct domain refs in app/cli
└── test_trading_graph_{state,routing,smoke}.py   # LangGraph stub-driven tests
```

## Running

```bash
uv run pytest -q                            # full suite
uv run pytest tests/services -q             # service-layer only
uv run pytest tests/api -q                  # HTTP layer only
uv run pytest tests/services/test_reports.py::test_risk_metrics_has_realistic_values -v
```

Current status: **252 passed, 3 pre-existing failures** in
`tests/test_database.py` (unrelated to the API refactor; documented at
the bottom).

## Fixtures + conventions

### Reads — use `data_demo/`

Service tests for read paths (`test_*.py` that don't mutate) hit the
checked-in demo dataset. The seeded demo portfolios are:

- `Demo Cash & CDs` — Cash + CD
- `Demo Retirement` — ETF-heavy
- `Demo Brokerage` — Mixed equity + crypto

Assert on **presence** (`"Demo Brokerage" in names`) rather than exact
counts, so the tests survive demo-seed tweaks.

### Mutations — use `tmp_path`

Anything that writes (create / delete / update / load-csv / collect /
record-trade / run-job) takes `tmp_path` and uses `str(tmp_path)` as
`data_dir`. Each test gets a fresh dir, so mutations never bleed between
tests or pollute `data_demo/`.

### yfinance monkeypatching

`collect_prices` and the production `collect_prices` job both call
`import yfinance as yf` lazily. Tests patch it via
`monkeypatch.setitem(sys.modules, "yfinance", fake_module)` where
`fake_module` exposes a `download(...)` returning a small DataFrame. See
`tests/services/test_prices.py:test_collect_prices_uses_yfinance_and_records_success`
for the canonical shape.

### Stub agent classes

Real `RiskAgent` / `WealthAgent` etc. instantiate `anthropic.Anthropic()`
which reads `ANTHROPIC_API_KEY`. Tests register a deterministic stub via
`src.services.agents.register_agent_class(kind, _StubAgent)` so the
session cache + chat flow can be exercised hermetically. The autouse
fixture also calls `reset_sessions()` between cases. See
`tests/services/test_agents.py` for the pattern.

### Stub production jobs

`src.production.JOB_REGISTRY` references real callables that hit yfinance
or the AttributionEngine. Tests monkeypatch the registry on **both**
`src.production` and `src.services.production` with a deterministic
success + failure pair. See `tests/services/test_production.py`.

### FastAPI TestClient

API tests:

```python
@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

DEMO_HEADERS = {"X-Data-Dir": "data_demo"}
```

For mutating endpoints:

```python
@pytest.fixture
def headers(tmp_path) -> dict[str, str]:
    return {"X-Data-Dir": str(tmp_path)}
```

The `X-Data-Dir` header is mandatory in tests — `tmp_path` is per-test,
so omitting it would dump writes into the default `data/` directory.

## What to test at which layer

| Concern | Layer | Why |
|---|---|---|
| Computation correctness | `tests/services` | Faster, no HTTP overhead |
| Error message phrasing | `tests/services` | Assertion on `match=` substrings — the API global handler depends on this |
| Status codes (200/201/204/400/404/409/422) | `tests/api` | The mapping is HTTP-layer concern |
| Request validation (pydantic) | `tests/api` | 422 happens before the service is called |
| Long-running / network calls | Skip or monkeypatch | Tests must run offline in under a few seconds |

## Layering ratchet

`tests/test_lint_domain_layering.py` counts whole-word references to
`Database`, `ReportingEngine`, `AttributionEngine`, `Collector`,
`Ingester`, `JobRunner` in `src/app.py` and `src/cli.py`. The counts are
capped per file by `MAX_DIRECT_REFS`. The companion `test_cap_is_not_too_loose`
test fails if the actual count is below the cap — forcing the ratchet
to travel one direction only.

When you migrate a site:
1. Run the test — it'll report the new lower count in the failure message.
2. Drop the cap in `MAX_DIRECT_REFS` accordingly.

## Pre-existing failures

```
FAILED tests/test_database.py::test_init_assets_has_correct_columns
FAILED tests/test_database.py::test_get_historical_prices_missing_ticker_skipped
FAILED tests/test_database.py::test_get_historical_prices_all_missing_returns_empty
```

These predate the API refactor work — confirmed by a stash + retest at
the start of the refactor branch. Don't treat them as new regressions.
Touching `src/database/database.py` to fix them is a separate slice.

## Adding a new test file

1. Pick the right subdir (`services/`, `api/`, or top-level).
2. Mirror an existing file's structure — fixtures, `_HEADERS` constants.
3. Use `tmp_path` if you mutate state.
4. Monkeypatch any network-touching module on `sys.modules`; never let a
   test reach the real internet.
5. Prefer **presence + bounds** assertions over exact values when
   testing against `data_demo/` — the demo seed can change.
6. For service-layer tests of caches / registries (agents, trading
   graph), add an autouse fixture that calls the relevant `reset_*()`
   helper between cases.

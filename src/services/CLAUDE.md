# Service layer

Pure-Python typed functions that wrap the domain modules
(`Database`, `ReportingEngine`, `AttributionEngine`, `Collector`,
`Benchmark` catalogue, agent classes, trading graph). Every client —
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
│   ├── benchmark.py
│   ├── portfolio.py
│   ├── price.py
│   ├── report.py
│   └── scenario.py
├── portfolios.py      # list / get / create / delete / load-csv / update-positions
├── prices.py          # latest / history / collect (yfinance)
├── reports.py         # risk / exposure / income / correlation / attribution + df helpers
├── scenarios.py       # catalogues + sector stress (+ df helper)
└── benchmarks.py      # catalogue + returns / stats / compare-to-portfolio
```

## Invariants (enforced by code review)

1. **No imports from `streamlit`, `click`, `fastapi`, or `uvicorn`.**
   Pydantic and pandas are fine. The service layer is framework-free.
2. **Functions take primitives and return pydantic models / primitives.**
   No DataFrame in public signatures — convert via the `*_to_dataframe`
   helpers (e.g. `income_report_to_dataframe`, `price_history_to_dataframe`,
   `stress_result_to_dataframe`, `covariance_to_dataframe`,
   `correlation_to_dataframe`) for in-process callers that want pandas.
3. **All Database construction goes through `_get_db(data_dir)`**, never
   `Database(data_dir)` directly. The LRU cache is shared per process.

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
also assert on substrings, so phrasing is double-pinned.

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

## Deferred work (per `API_REFACTOR_PLAN.md`)

Some logic deliberately doesn't live here yet:

- **Monte Carlo wealth projection** lives in `src/agent/wealth_skills.py`
  (~150 lines of stats). Will migrate when we touch agents (slice 7).
- **Daily-metrics refresh** (writing `daily_*.parquet`) stays in
  `src/attribution.py`. The reports service only reads. Refresh is
  slice 11 (production).
- **Trades CRUD** and **groups CRUD** — slices 6 & 8.
- **`db.save_portfolio()` at the trade-form create-if-missing fallback**
  in `src/app.py` line ~3009 — migrates with the trades slice.
- **`db.get_portfolio()`** is still called directly in `src/app.py` in
  ~15 places; those consumers want a domain `Portfolio` object (not a
  `PortfolioDetail` pydantic). They migrate when downstream code that
  uses lookthrough / agent skills / metrics is touched.

## Tests

Mirror the module names — `tests/services/test_<module>.py` (logic) and
`tests/api/test_<module>.py` (HTTP semantics). The service tests use
`data_demo` for reads and `tmp_path` for mutations. `yfinance` is
monkeypatched on `sys.modules` for hermetic `collect_prices` tests.

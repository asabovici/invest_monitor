# HTTP API

invest-monitor exposes a typed FastAPI surface in front of the service
layer. Streamlit, the Click CLI, and any future frontend all consume
the same endpoints.

> Architecture, layout, and design rationale live in
> [`API_REFACTOR_PLAN.md`](https://github.com/anthropics/invest_monitor/blob/main/API_REFACTOR_PLAN.md)
> at the repo root.

## Running the server

```bash
uv run invest-monitor serve                                  # 127.0.0.1:8000
uv run invest-monitor serve --port 9000
uv run invest-monitor serve --host 0.0.0.0 --port 8000       # bind all interfaces
uv run invest-monitor serve --data-dir data_demo             # set INVEST_MONITOR_DATA_DIR
uv run invest-monitor serve --reload                         # dev auto-reload
```

The server uses [`uvicorn`](https://www.uvicorn.org/) under the hood;
the CLI just wraps `uvicorn.run("src.api.main:app", ...)`.

Once running:

- **OpenAPI JSON** — `GET /openapi.json`
- **Swagger UI** — `GET /docs`
- **ReDoc** — `GET /redoc`
- **Health check** — `GET /health` returns `{"status": "ok"}`

## Endpoint surface

The full schema lives at `/openapi.json`. High-level groupings:

| Prefix | Resource |
|---|---|
| `/portfolios` | List / detail / create / delete; `POST /load-csv`; `PUT /{name}/positions`; `GET/PUT /{name}/groups`; `GET /{name}/trades` |
| `/prices` | `GET /latest`, `GET /history`, `POST /collect` (long-running) |
| `/reports/{kind}/{portfolio}` | `risk`, `exposure`, `income`, `correlation`, `attribution` |
| `/scenarios` | `GET /stress`, `/mc`, `/regimes` listings; `POST /stress/{portfolio}` |
| `/benchmarks` | List + `/{name}/{returns,stats}` + `/compare/{portfolio}` |
| `/groups` | CRUD; `PUT /{name}/members` atomic replace; per-member add/remove |
| `/trades` | `GET` (with `?portfolio_name=` filter), `POST` to record |
| `/agents` | `/kinds`; `POST /{kind}/sessions`; per-session message / prime / history / end |
| `/summaries` | List / get / delete; `POST /from-session` |
| `/trading-graph/runs` | Start / get / resume / end (HITL pause is a real REST step) |
| `/production` | `/jobs`, `/jobs/{name}/run`, `/run-due`, `/runs`, `/metrics-refresh` |
| `/health` | Liveness probe |

## Conventions

### `X-Data-Dir` header

Every endpoint that touches storage takes an `X-Data-Dir` header that
picks the active dataset:

```bash
# Live dataset (default)
curl http://localhost:8000/portfolios

# Demo dataset
curl -H 'X-Data-Dir: data_demo' http://localhost:8000/portfolios
```

Resolution order: `X-Data-Dir` header → `INVEST_MONITOR_DATA_DIR` env
var → `"data"` fallback. Same mental model as the dashboard's live/demo
toggle.

### Error shape

Service-layer `ValueError`s are translated by a global handler based on
the message phrasing:

| Message phrase | HTTP status |
|---|---|
| `not found` / `does not exist` | 404 |
| `already exists` | 409 |
| anything else | 400 |

Pydantic validation errors surface as 422 with FastAPI's standard
`{"detail": [...]}` shape.

### DataFrames over JSON

Tabular responses (`/prices/history`, `/reports/correlation/...`) use a
column-aligned shape:

```json
{
  "tickers": ["AAPL", "MSFT"],
  "dates":   ["2026-01-01", "2026-01-02"],
  "prices":  {"AAPL": [150.0, 151.0], "MSFT": [380.0, 382.0]}
}
```

Reconstruct into pandas with
`pd.DataFrame(payload["prices"], index=pd.to_datetime(payload["dates"]))`.

NaN handling is shape-dependent:

- **Matrices** (covariance, correlation, ticker × ticker dicts) →
  `NaN` becomes `0.0`.
- **Time series** (prices, returns, drawdowns) → `NaN` becomes `null`
  so the date index stays aligned.

### Process-local sessions

`/agents/sessions/{id}` and `/trading-graph/runs/{id}` are keyed on
UUIDs held in process-local dicts. Sessions and runs do **not**
survive a uvicorn restart — clients should treat the IDs as
short-lived. Persistent context belongs in `/summaries`.

### Long-running endpoints

These are synchronous; a single request can hold a worker for minutes:

- `POST /prices/collect`
- `POST /production/jobs/{name}/run` (especially `collect_prices` and
  `refresh_attribution`)
- `POST /production/run-due`
- `POST /production/metrics-refresh`

For production workloads use the CLI (`invest-monitor collect`,
`invest-monitor production run`, etc.) or wire a systemd timer in.
The rate-limit middleware below caps how often a single client can
hit them over HTTP.

## Optional hardening (env-var-gated)

The middleware stack is opt-in via environment variables. Without
them, the server behaves exactly like the original loopback-only
development setup (no auth, no rate limit, any `X-Data-Dir`). Set
**all three** before exposing the API to a network:

| Env var | Effect |
|---|---|
| `INVEST_MONITOR_API_KEY` | Enables `APIKeyAuthMiddleware`. Every request except `/health`, `/docs`, `/redoc`, `/openapi.json` requires `Authorization: Bearer <key>` or `X-API-Key: <key>`. Constant-time comparison via `hmac.compare_digest`. |
| `INVEST_MONITOR_ALLOWED_DATA_DIRS` | Comma-separated allowlist for `X-Data-Dir`. Off-list values → 400. Validates the env-var default too. |
| `INVEST_MONITOR_RATE_LIMIT` | Token bucket on the long-running endpoints. Format `"N/seconds"` (e.g. `10/60`) or just `"N"` (default window 60 s). Different API keys get separate buckets via `sha256(key)[:16]`. 429 with `Retry-After`. |

### Recommended production config

```bash
export INVEST_MONITOR_API_KEY="$(openssl rand -hex 32)"
export INVEST_MONITOR_ALLOWED_DATA_DIRS="data"
export INVEST_MONITOR_DATA_DIR="data"
export INVEST_MONITOR_RATE_LIMIT="10/60"

uv run invest-monitor serve --host 0.0.0.0
```

### Middleware ordering

Execution order is **auth → rate-limit → body-size → app** so:

- Anonymous traffic gets 401 (not 429).
- Rate-limit budget isn't burned parsing oversized bodies.
- Bodies above 10 MB get 413 before reaching the route.

The full design and the remaining open items (per-principal session
ownership for agents/trading-graph, §11.4) are tracked in
`API_REFACTOR_PLAN.md` §11.

## Programmatic clients

### `httpx` / Python

```python
import httpx

client = httpx.Client(
    base_url="http://localhost:8000",
    headers={
        "X-Data-Dir": "data",
        "Authorization": "Bearer your-key-here",
    },
)
portfolios = client.get("/portfolios").json()
risk = client.get(f"/reports/risk/{portfolios[0]['name']}").json()
```

### `curl`

```bash
KEY=your-key-here
H_AUTH="Authorization: Bearer $KEY"
H_DIR="X-Data-Dir: data"

curl -H "$H_AUTH" -H "$H_DIR" http://localhost:8000/portfolios
curl -H "$H_AUTH" -H "$H_DIR" \
  "http://localhost:8000/prices/history?tickers=AAPL,MSFT&start=2026-01-01"
```

### TypeScript / browser clients

The OpenAPI schema at `/openapi.json` is consumable by every standard
generator — e.g. `openapi-typescript`, `openapi-fetch`, or Stainless.

## Streamlit and the CLI in-process

The dashboard and CLI **don't** go through HTTP — they import the
service layer (`src.services.*`) directly and run in the same process.
The FastAPI app is what an external client uses; Streamlit and Click
get the same logic without the serialisation overhead.

This is the whole point of the architecture: business logic lives in
`src/services/`, the HTTP layer is just a thin wrapper. See
[Developer Guide](developer.md) for the layout and the layering
invariants.

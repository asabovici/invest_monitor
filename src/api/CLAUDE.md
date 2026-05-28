# FastAPI HTTP layer

This is the only place in the codebase that knows about HTTP. Routers are
thin: parse the request, call a service function, return the result.
Business logic lives in `src/services/`.

## Layout

```
src/api/
├── main.py              # `app = FastAPI(...)`, mounts middleware/routers/handlers
├── deps.py              # Shared FastAPI dependencies (data_dir_dep)
├── errors.py            # Global ValueError → HTTP exception handler
├── middleware.py        # Body-size-limit ASGI middleware
├── routers/             # One file per resource
│   ├── portfolios.py
│   ├── prices.py
│   ├── reports.py
│   ├── scenarios.py
│   └── benchmarks.py
└── schemas/             # Back-compat re-export shim → src/services/schemas/
```

Boot with `uvicorn src.api.main:app` or `invest-monitor serve`.

## Conventions

### Routers do not catch ValueError

`src/api/errors.py:register_error_handlers` installs a global handler that
translates service-layer `ValueError`s based on the message phrasing:

| Phrase in message | HTTP status |
|---|---|
| `"not found"` or `"does not exist"` | 404 |
| `"already exists"` | 409 |
| anything else | 400 |

Routers stay clean — just call the service and return. If you need a new
status code, **change the service message** rather than reintroducing
`try/except` in the router. Phrasing is also documented in
`src/services/__init__.py`.

### `X-Data-Dir` header

Every endpoint that touches storage takes `data_dir: Annotated[str,
Depends(data_dir_dep)]`. The dependency resolves the data dir from:

1. `X-Data-Dir` request header, if present.
2. `INVEST_MONITOR_DATA_DIR` env var.
3. `"data"` fallback.

Mirrors the Streamlit sidebar's live/demo toggle. No URL changes needed
to switch datasets.

### Schemas

The pydantic models live at `src/services/schemas/` — that's the canonical
home. `src/api/schemas/__init__.py` re-binds those submodules into
`sys.modules` so both import paths resolve to the same class (back-compat
with anything that already imports `from src.api.schemas.X`). New code
should prefer the `src.services.schemas` path.

### `{name:path}` for slashes

The benchmark catalogue has names like `60/40 Classic`. Routers use the
Starlette `:path` converter (`/{name:path}/...`) so URL-encoded slashes
survive routing. Every such route has a fixed suffix (`/returns`,
`/stats`, `/compare/{portfolio_name}`) so there's no parsing ambiguity.

### Body-size cap

`BodySizeLimitMiddleware` (10 MB default) sits in front of every route.
Two layers — `Content-Length` short-circuit + streamed-receive wrapper —
both return `413` with a JSON `detail`. The cap protects
`POST /portfolios/load-csv` mainly; non-CSV endpoints all fit in well
under a megabyte. Bump the cap by passing `max_bytes=...` when mounting.

### Long-running endpoints

`POST /prices/collect` is **synchronous**. It runs a yfinance download
per ticker; large portfolios can hold a worker for minutes. The top-level
app description and the route docstring both flag this. A streaming /
background-job version is planned with the production-jobs slice.

## Adding a new resource

1. Create or extend `src/services/<resource>.py` with the typed functions.
2. Add a pydantic schema at `src/services/schemas/<resource>.py`.
3. Add `src/api/routers/<resource>.py`:
   - `router = APIRouter(prefix="/<resource>", tags=["<resource>"])`
   - Thin functions: no try/except, just call the service.
   - Take `data_dir: Annotated[str, Depends(data_dir_dep)]`.
4. Mount in `src/api/main.py`: `app.include_router(<resource>.router)`.
5. Tests at `tests/api/test_<resource>.py` using `fastapi.testclient.TestClient`.
   See `tests/api/test_portfolios.py` for the shape.

## Layering invariant

**The API layer never imports `src.database`, `src.reporting`,
`src.attribution`, etc. directly.** Always go through `src/services/`.
If you find yourself reaching past the service layer from a router,
that's a missing service function.

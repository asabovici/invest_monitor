"""FastAPI app entrypoint.

Boot with ``uvicorn src.api.main:app`` or via the CLI:
``invest-monitor serve``.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.api.errors import register_error_handlers
from src.api.middleware import DEFAULT_MAX_BODY_BYTES, BodySizeLimitMiddleware
from src.api.routers import (
    agents,
    benchmarks,
    groups,
    portfolios,
    prices,
    reports,
    scenarios,
    summaries,
    trades,
    trading_graph,
)

app = FastAPI(
    title="invest-monitor API",
    version="0.1.0",
    description=(
        "Typed HTTP surface in front of the invest-monitor service layer. "
        "Streamlit, the Click CLI, and any future frontend all consume "
        "the same endpoints.\n\n"
        f"Request bodies are capped at {DEFAULT_MAX_BODY_BYTES:,} bytes "
        "(see ``src.api.middleware``). Note that ``POST /prices/collect`` is "
        "synchronous and long-running — each ticker triggers an outbound "
        "yfinance download, so a single request can hold a worker for "
        "minutes when run against a large portfolio."
    ),
)

app.add_middleware(BodySizeLimitMiddleware, max_bytes=DEFAULT_MAX_BODY_BYTES)
register_error_handlers(app)

app.include_router(portfolios.router)
app.include_router(prices.router)
app.include_router(reports.router)
app.include_router(scenarios.router)
app.include_router(benchmarks.router)
app.include_router(groups.router)
app.include_router(trades.router)
app.include_router(agents.router)
app.include_router(summaries.router)
app.include_router(trading_graph.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe. Returns ``{'status': 'ok'}``."""
    return {"status": "ok"}

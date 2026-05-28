"""FastAPI app entrypoint.

Boot with ``uvicorn src.api.main:app`` or via the CLI:
``invest-monitor serve``.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.api.routers import benchmarks, portfolios, prices, reports, scenarios

app = FastAPI(
    title="invest-monitor API",
    version="0.1.0",
    description=(
        "Typed HTTP surface in front of the invest-monitor service layer. "
        "Streamlit, the Click CLI, and any future frontend all consume "
        "the same endpoints."
    ),
)

app.include_router(portfolios.router)
app.include_router(prices.router)
app.include_router(reports.router)
app.include_router(scenarios.router)
app.include_router(benchmarks.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe. Returns ``{'status': 'ok'}``."""
    return {"status": "ok"}

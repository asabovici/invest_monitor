"""FastAPI app entrypoint.

Boot with ``uvicorn src.api.main:app`` or via the CLI:
``invest-monitor serve``.
"""

from __future__ import annotations

from fastapi import FastAPI

from src.api.routers import portfolios

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


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe. Returns ``{'status': 'ok'}``."""
    return {"status": "ok"}

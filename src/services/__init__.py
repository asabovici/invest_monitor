"""Pure-Python service layer for invest-monitor.

The service layer wraps the domain objects (Database, ReportingEngine,
AttributionEngine, Agent classes, trading_graph) behind typed, framework-free
functions. Clients — Streamlit, the Click CLI, the FastAPI app, and any
future frontend — call into this layer instead of touching the domain
modules directly.

Invariants:
- No imports from streamlit / click / fastapi / uvicorn.
- Functions take primitive args (paths, strings, numbers) and return
  pydantic models or primitives. No DataFrames in public signatures —
  serialise via the shared helpers when needed.
- Exceptions are domain-meaningful: use ``ValueError`` for "not found"
  / bad input. API layer translates these to HTTP status codes.
"""

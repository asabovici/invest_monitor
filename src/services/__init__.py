"""Pure-Python service layer for invest-monitor.

The service layer wraps the domain objects (Database, ReportingEngine,
AttributionEngine, Agent classes, trading_graph) behind typed, framework-free
functions. Clients — Streamlit, the Click CLI, the FastAPI app, and any
future frontend — call into this layer instead of touching the domain
modules directly.

Invariants
----------
- No imports from streamlit / click / fastapi / uvicorn.
- Functions take primitive args (paths, strings, numbers) and return
  pydantic models (canonical home: ``src.services.schemas``) or primitives.
  No DataFrames in public signatures — convert via the shared
  ``*_to_dataframe`` helpers when an in-process caller wants pandas.
- Exceptions are domain-meaningful: services raise ``ValueError`` with one
  of the recognised phrases below; the FastAPI layer translates those into
  HTTP status codes via the global handler in ``src.api.errors``.

ValueError phrasing convention
------------------------------
- "not found" / "does not exist"  → 404
- "already exists"                → 409
- anything else                   → 400

Stay consistent with these phrasings when raising — both the API mapping
and the service-layer tests depend on them.

NaN / missing-data convention
-----------------------------
Pandas / numpy intermediate values often contain ``NaN``. Pick one
representation per shape:

- **Matrices** (covariance, correlation, square ticker × ticker dicts):
  ``NaN`` → ``0.0``. Implemented in ``services.reports._matrix_to_dict``.
  Rationale: a missing covariance entry is informationally equivalent to
  "no co-movement" for downstream consumers, and zero is JSON-clean.

- **Time series** (price history, daily returns, cumulative returns,
  benchmark vs portfolio overlays): ``NaN`` → ``None``. The series stays
  aligned to the date index so callers can rebuild a DataFrame without
  re-aligning, while real gaps stay distinguishable from genuine zeros.

If you add a new endpoint, pick the side that matches the data shape
and document it in the schema docstring.
"""

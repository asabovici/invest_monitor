"""Centralised mapping from service-layer exceptions to HTTP responses.

The service layer raises plain ``ValueError`` with one of a handful of
recognisable phrasings (see below). Rather than re-implementing the same
``try/except`` block in every router, ``register_error_handlers`` wires
a single exception handler that does the mapping once.

Phrase → status code:
    "not found"         → 404
    "does not exist"    → 404
    "already exists"    → 409
    anything else       → 400

Keep service-layer error messages aligned with these phrases so the
mapping stays predictable. The phrasing convention is enforced by the
service-layer tests, which assert on specific substrings.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


def _status_for_value_error(message: str) -> int:
    lower = message.lower()
    if "already exists" in lower:
        return status.HTTP_409_CONFLICT
    if "not found" in lower or "does not exist" in lower:
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


def register_error_handlers(app: FastAPI) -> None:
    """Attach the shared ValueError → HTTP handler to ``app``."""

    @app.exception_handler(ValueError)
    def _handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
        msg = str(exc) or "Bad request"
        return JSONResponse(
            status_code=_status_for_value_error(msg),
            content={"detail": msg},
        )

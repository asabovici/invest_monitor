"""Shared FastAPI dependencies.

For now: only the active data directory, resolved from an ``X-Data-Dir``
header with a server-side default. Mirrors the dashboard's live/demo
toggle without baking the choice into URLs.

Path-traversal guard
--------------------
The ``X-Data-Dir`` header is client-supplied. Without protection a caller
could point the server at any filesystem path the process can read or
write (``/etc``, ``/home/<user>``, ``../somewhere`` …). When the
``INVEST_MONITOR_ALLOWED_DATA_DIRS`` env var is set to a comma-separated
list, the resolved data dir must match one of the entries; otherwise the
dep raises ``HTTPException(400)``. When the env var is unset (the
default), no enforcement happens — keeping tests / dev unchanged while
making the production setup explicit.

The allowlist applies to the env-var default too, so a misconfigured
``INVEST_MONITOR_DATA_DIR`` can't slip through.

Allowlist matching is **strict string equality**. ``data`` is not the
same as ``data/`` or ``./data``: write the canonical path you'd pass to
``Database(...)`` and don't decorate it. The allowlist does **not**
resolve symlinks; if ``data/`` is a symlink to ``/etc``, the symlink
target is what gets read — that's the admin's responsibility.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException, status

_DEFAULT_DATA_DIR_ENV = "INVEST_MONITOR_DATA_DIR"
_ALLOWED_DATA_DIRS_ENV = "INVEST_MONITOR_ALLOWED_DATA_DIRS"
_FALLBACK_DATA_DIR = "data"


def _server_default_data_dir() -> str:
    return os.environ.get(_DEFAULT_DATA_DIR_ENV, _FALLBACK_DATA_DIR)


def _allowed_data_dirs() -> frozenset[str] | None:
    """Configured allowlist of data dirs. ``None`` means no enforcement."""
    raw = os.environ.get(_ALLOWED_DATA_DIRS_ENV, "").strip()
    if not raw:
        return None
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def data_dir_dep(
    x_data_dir: Annotated[str | None, Header(alias="X-Data-Dir")] = None,
) -> str:
    """Resolve the data dir for this request.

    Precedence:
    1. ``X-Data-Dir`` request header
    2. ``INVEST_MONITOR_DATA_DIR`` env var
    3. Fallback ``"data"``

    If ``INVEST_MONITOR_ALLOWED_DATA_DIRS`` is configured, the resolved
    value must appear in the list; otherwise the dep raises a 400.
    """
    resolved = x_data_dir or _server_default_data_dir()
    allowed = _allowed_data_dirs()
    if allowed is not None and resolved not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Data dir {resolved!r} is not in the configured allowlist. "
                f"Set INVEST_MONITOR_ALLOWED_DATA_DIRS to include it, or omit "
                f"the X-Data-Dir header."
            ),
        )
    return resolved

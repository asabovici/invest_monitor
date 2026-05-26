"""Shared FastAPI dependencies.

For now: only the active data directory, resolved from an ``X-Data-Dir``
header with a server-side default. Mirrors the dashboard's live/demo
toggle without baking the choice into URLs.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header

_DEFAULT_DATA_DIR_ENV = "INVEST_MONITOR_DATA_DIR"
_FALLBACK_DATA_DIR = "data"


def _server_default_data_dir() -> str:
    return os.environ.get(_DEFAULT_DATA_DIR_ENV, _FALLBACK_DATA_DIR)


def data_dir_dep(
    x_data_dir: Annotated[str | None, Header(alias="X-Data-Dir")] = None,
) -> str:
    """Resolve the data dir for this request.

    Precedence:
    1. ``X-Data-Dir`` request header
    2. ``INVEST_MONITOR_DATA_DIR`` env var
    3. Fallback ``"data"``
    """
    return x_data_dir or _server_default_data_dir()

"""Internal helper: cache ``Database`` instances per ``data_dir``.

Constructing ``Database`` is cheap (it runs ``_init_store`` which mostly
``os.makedirs``), but doing it on every service call still costs a stack of
syscalls. With only a handful of active data dirs at runtime (typically 1
or 2 — live and demo), a small LRU is plenty.
"""

from __future__ import annotations

from functools import lru_cache

from src.database import Database


@lru_cache(maxsize=8)
def _get_db(data_dir: str) -> Database:
    """Return a cached ``Database`` for ``data_dir``.

    Cache key is the literal data_dir string — callers should pass the
    normalised path. The cache is process-local; a new uvicorn worker
    starts fresh.
    """
    return Database(data_dir)


def reset_db_cache() -> None:
    """Clear the cached ``Database`` instances. Tests use this between cases."""
    _get_db.cache_clear()

"""Token-bucket rate limiting for long-running endpoints.

Auth (``src/api/auth.py``) gates *who* may call the API. This middleware
caps *how often* an authenticated caller may invoke the synchronous,
long-running endpoints — the ones that hit yfinance or run the
attribution engine and can hold a worker for minutes. Together they
close the §11.3 hardening item from ``API_REFACTOR_PLAN.md``.

Configuration
-------------

Set ``INVEST_MONITOR_RATE_LIMIT`` to enable the middleware. Two forms:

- ``"N/seconds"`` — N tokens per ``seconds``-second sliding window
  (e.g. ``"10/60"`` = 10 requests per minute).
- ``"N"`` — N tokens per minute (60-second default window).

When the env var is **unset** (the default), the middleware is a no-op
and traffic flows straight through. Existing tests and local dev stay
unchanged.

Scope
-----

Only these paths consume tokens — everything else (reads, CRUD,
``/health``, etc.) is unlimited:

- ``POST /prices/collect``
- ``POST /production/jobs/<name>/run``
- ``POST /production/run-due``
- ``POST /production/metrics-refresh``

Client identification
---------------------

Each token bucket is keyed by a stable client identifier:

1. ``sha256(api_key)[:16]`` when ``Authorization: Bearer <key>`` or
   ``X-API-Key`` is present — so different authenticated clients each
   get their own budget. The key is hashed to avoid storing the
   plaintext secret in the bucket dict.
2. ``ip:<remote>`` when no credential is present.
3. ``"anonymous"`` as a last resort (ASGI scope without client info).

State
-----

Buckets live in a process-local dict. Behind a load balancer each
instance has its own buckets — divide the limit by the number of
instances or move to a shared backend (Redis) in a future slice.

Ordering
--------

In ``src/api/main.py`` this middleware is mounted **between** auth and
body-size: auth fires first (so anonymous traffic gets 401, not 429),
then rate-limit (long-running endpoints), then body-size. See the
ordering comment in ``main.py`` for the FastAPI gotcha (last-added is
outermost).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send


_RATE_LIMIT_ENV = "INVEST_MONITOR_RATE_LIMIT"
_DEFAULT_WINDOW_SECONDS = 60
_AUTH_HEADER = "authorization"
_API_KEY_HEADER = "x-api-key"
_BEARER_PREFIX = "bearer "

_EXACT_LIMITED_PATHS = frozenset({
    "/prices/collect",
    "/production/run-due",
    "/production/metrics-refresh",
})

_logger = logging.getLogger(__name__)


# ── Config parsing ───────────────────────────────────────────────────────────


def _parse_limit(raw: str | None) -> tuple[int, int] | None:
    """Parse ``INVEST_MONITOR_RATE_LIMIT`` into ``(tokens, window_seconds)``.

    Returns ``None`` when the env var is unset / empty / malformed; the
    middleware treats that as "off" and passes everything through.
    A malformed value also logs a warning so an admin notices.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        if "/" in s:
            n_str, w_str = s.split("/", 1)
            n, w = int(n_str.strip()), int(w_str.strip())
        else:
            n, w = int(s), _DEFAULT_WINDOW_SECONDS
    except ValueError:
        _logger.warning(
            "INVEST_MONITOR_RATE_LIMIT=%r is malformed; expected 'N' or 'N/seconds'. "
            "Rate limiting stays disabled.",
            raw,
        )
        return None
    if n <= 0 or w <= 0:
        _logger.warning(
            "INVEST_MONITOR_RATE_LIMIT=%r resolves to non-positive values; "
            "rate limiting stays disabled.",
            raw,
        )
        return None
    return n, w


# ── Path scope ───────────────────────────────────────────────────────────────


def _is_limited(path: str) -> bool:
    """Return True for the synchronous, long-running endpoints."""
    if path in _EXACT_LIMITED_PATHS:
        return True
    # /production/jobs/<name>/run — name is variable.
    if path.startswith("/production/jobs/") and path.endswith("/run"):
        return True
    return False


# ── Client identification ───────────────────────────────────────────────────


def _client_id(scope: Scope, headers: dict[str, str]) -> str:
    """Stable bucket key for the requesting client.

    Preference: API key (hashed) → client IP → ``"anonymous"``.
    """
    auth = headers.get(_AUTH_HEADER)
    if auth and auth.lower().startswith(_BEARER_PREFIX):
        token = auth[len(_BEARER_PREFIX):].strip()
        if token:
            return f"key:{_hash(token)}"
    api_key = headers.get(_API_KEY_HEADER)
    if api_key:
        return f"key:{_hash(api_key)}"
    client = scope.get("client")
    if client and client[0]:
        return f"ip:{client[0]}"
    return "anonymous"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


# ── Token bucket ─────────────────────────────────────────────────────────────


class _TokenBucketStore:
    """Process-local map of ``client_id → (tokens, last_refill_monotonic)``.

    Thread-safe. Allocations are O(unique clients) for the lifetime of
    the process — fine for the workload here, but the docstring of the
    middleware module spells out the load-balancer caveat.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def acquire(
        self,
        client_id: str,
        capacity: int,
        refill_rate_per_second: float,
        now: float,
    ) -> tuple[bool, float]:
        """Try to consume one token. Returns ``(allowed, retry_after_seconds)``.

        On allow, ``retry_after_seconds`` is 0. On reject, it's the time
        until the next token would be available — sent in ``Retry-After``.
        """
        with self._lock:
            tokens, last = self._buckets.get(client_id, (float(capacity), now))
            elapsed = max(0.0, now - last)
            tokens = min(float(capacity), tokens + elapsed * refill_rate_per_second)
            if tokens >= 1.0:
                self._buckets[client_id] = (tokens - 1.0, now)
                return True, 0.0
            # Not enough — how long until one token?
            deficit = 1.0 - tokens
            retry_after = deficit / refill_rate_per_second if refill_rate_per_second > 0 else 1.0
            self._buckets[client_id] = (tokens, now)
            return False, retry_after

    def clear(self) -> None:
        """Drop all buckets — tests call this between cases."""
        with self._lock:
            self._buckets.clear()


# Module-level store so tests can reset it via ``reset_buckets()``.
_store = _TokenBucketStore()


def reset_buckets() -> None:
    """Clear the token-bucket cache. Tests call this between cases."""
    _store.clear()


# ── Middleware ───────────────────────────────────────────────────────────────


class RateLimitMiddleware:
    """Token-bucket rate limit on long-running endpoints.

    No-op when ``INVEST_MONITOR_RATE_LIMIT`` is unset. Otherwise charges
    one token per limited request and returns 429 with ``Retry-After``
    when the bucket is empty.
    """

    def __init__(
        self,
        app: ASGIApp,
        store: _TokenBucketStore | None = None,
        limited_paths: Iterable[str] | None = None,
    ) -> None:
        self.app = app
        # The shared module-level store is the default; tests can pass
        # an isolated one to avoid cross-test bleed.
        self._store = store if store is not None else _store
        # Override hook for tests — defaults to the production set.
        self._extra_paths = frozenset(limited_paths or ())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        config = _parse_limit(os.environ.get(_RATE_LIMIT_ENV))
        if config is None:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not (_is_limited(path) or path in self._extra_paths):
            await self.app(scope, receive, send)
            return

        capacity, window = config
        refill_rate = capacity / window

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        client_id = _client_id(scope, headers)

        allowed, retry_after = self._store.acquire(
            client_id=client_id,
            capacity=capacity,
            refill_rate_per_second=refill_rate,
            now=time.monotonic(),
        )
        if allowed:
            await self.app(scope, receive, send)
            return

        await _respond_429(send, retry_after_seconds=max(1, int(retry_after + 0.999)))


async def _respond_429(send: Send, *, retry_after_seconds: int) -> None:
    body = b'{"detail":"Rate limit exceeded."}'
    await send({
        "type": "http.response.start",
        "status": 429,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"retry-after", str(retry_after_seconds).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})

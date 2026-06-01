"""Optional API-key authentication middleware.

When ``INVEST_MONITOR_API_KEY`` is set in the server's environment,
every request must present a matching credential in one of:

- ``Authorization: Bearer <key>``
- ``X-API-Key: <key>``

**Credential precedence.** When the ``Authorization`` header is present
and starts with ``Bearer`` (case-insensitive), its token is used and
``X-API-Key`` is ignored — so a client that picks the Bearer scheme
can't fall back to ``X-API-Key`` mid-request. If ``Authorization`` is
absent or uses a different scheme (``Basic``, etc.), the middleware
falls through to ``X-API-Key``.

Requests missing or carrying the wrong credential get ``401`` with a
``WWW-Authenticate`` header pointing at the Bearer scheme.

Exempt paths (always allowed, no credential required):

- ``/health`` — liveness probes shouldn't need auth
- ``/docs``, ``/redoc``, ``/openapi.json`` — interactive API browsing

When the env var is **unset** (the default), the middleware is a no-op
and traffic flows straight through. This preserves the original
loopback-only behaviour and keeps tests/dev unchanged.

**Auth alone is not enough.** This middleware shuts the door on
anonymous traffic but doesn't throttle authenticated callers. Long-
running endpoints (``/prices/collect``, ``/production/*/run``,
``/production/metrics-refresh``) can still be hammered to exhaustion by
a single authenticated client. See ``API_REFACTOR_PLAN.md`` §11.3 for
the rate-limiting follow-up.

Pair with the allowlist in ``src/api/deps.py:data_dir_dep`` (driven by
``INVEST_MONITOR_ALLOWED_DATA_DIRS``) so an authenticated caller still
can't point the server at arbitrary filesystem paths.
"""

from __future__ import annotations

import hmac
import logging
import os
from functools import lru_cache

from starlette.types import ASGIApp, Receive, Scope, Send


_API_KEY_ENV = "INVEST_MONITOR_API_KEY"
_AUTH_HEADER = "authorization"
_API_KEY_HEADER = "x-api-key"
_BEARER_PREFIX = "bearer "  # lowercase; matched case-insensitively
_MIN_RECOMMENDED_KEY_BYTES = 32

_EXEMPT_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})

_logger = logging.getLogger(__name__)


class APIKeyAuthMiddleware:
    """Reject unauthenticated requests when an API key is configured.

    Comparison uses ``hmac.compare_digest`` so the runtime doesn't leak
    the key one byte at a time via response-time differences.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        configured_key = os.environ.get(_API_KEY_ENV)
        if not configured_key:
            await self.app(scope, receive, send)
            return

        _warn_if_short(configured_key)

        path = scope.get("path", "")
        if path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        presented = _extract_key(headers)
        if presented is not None and hmac.compare_digest(presented, configured_key):
            await self.app(scope, receive, send)
            return

        await _respond_401(send)


def _extract_key(headers: dict[str, str]) -> str | None:
    """Pull the credential from ``Authorization: Bearer`` or ``X-API-Key``.

    The Bearer scheme name is matched case-insensitively, so
    ``Authorization: bearer xyz`` works as well as ``Bearer xyz``.
    """
    auth = headers.get(_AUTH_HEADER)
    if auth and auth.lower().startswith(_BEARER_PREFIX):
        return auth[len(_BEARER_PREFIX):].strip() or None
    return headers.get(_API_KEY_HEADER)


@lru_cache(maxsize=4)
def _warn_if_short(key: str) -> None:
    """Log a one-shot advisory when the configured key is short.

    ``lru_cache`` keys on the value, so cycling between different keys
    (e.g. in tests) each get one warning at most. Cap of 4 prevents
    pathological test-suite churn from blowing the cache.
    """
    if len(key) < _MIN_RECOMMENDED_KEY_BYTES:
        _logger.warning(
            "INVEST_MONITOR_API_KEY is %d characters (< %d recommended). "
            "Use a long random secret for any network-exposed deployment.",
            len(key),
            _MIN_RECOMMENDED_KEY_BYTES,
        )


async def _respond_401(send: Send) -> None:
    body = b'{"detail":"Authentication required."}'
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b'Bearer realm="invest-monitor"'),
        ],
    })
    await send({"type": "http.response.body", "body": body})

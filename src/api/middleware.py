"""ASGI middleware for the invest-monitor API.

Currently exposes a single concern: capping request body size. Starlette
has no built-in size limit; without one a misbehaving client can pin a
worker by streaming a multi-GB upload to ``/portfolios/load-csv`` or any
other JSON endpoint. We enforce the limit by inspecting ``Content-Length``
on the way in and by wrapping the receive callable so streaming uploads
hit the same cap.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Default 10 MB — well above any sane portfolio CSV / JSON request, well
# below "I can DoS the server by holding a worker for hours".
DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024


class BodySizeLimitMiddleware:
    """Reject HTTP requests whose body exceeds ``max_bytes``.

    Two layers of defence:
    1. ``Content-Length`` header check — short-circuits oversized requests
       before any body is read.
    2. Receive-wrapping — chunked / streamed requests are tallied as bytes
       arrive; the connection is closed with 413 once the cap is crossed.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        cl = headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > self.max_bytes:
            await _respond_413(send, self.max_bytes)
            return

        received = 0
        max_bytes = self.max_bytes
        over_limit = False

        async def receive_wrapper() -> Message:
            nonlocal received, over_limit
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body") or b""
                received += len(body)
                if received > max_bytes:
                    over_limit = True
            return message

        async def send_wrapper(message: Message) -> None:
            if over_limit:
                # Replace whatever the app is sending with a 413; further sends
                # are suppressed so we don't double-respond.
                if message["type"] == "http.response.start":
                    await _respond_413(send, max_bytes)
                return
            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)


async def _respond_413(send: Send, max_bytes: int) -> None:
    body = (
        b'{"detail":"Request body exceeds the '
        + str(max_bytes).encode()
        + b'-byte limit."}'
    )
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})

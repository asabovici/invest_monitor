"""FastAPI application exposing the invest-monitor service layer over HTTP.

The API is the only place in the codebase that knows about HTTP. Routers
are thin: parse the request, call a service function, serialise the
response. All business logic lives in ``src/services``.
"""

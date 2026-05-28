"""Canonical pydantic schemas for the service layer.

These models are the single source of truth for the shape of service-layer
returns. The API layer re-exports them for OpenAPI/FastAPI routing; clients
that prefer one import path can use either:

    from src.services.schemas.portfolio import PortfolioDetail
    # or
    from src.api.schemas.portfolio import PortfolioDetail   # back-compat
"""

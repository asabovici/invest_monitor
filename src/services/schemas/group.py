"""Pydantic schemas for portfolio-group endpoints (slice 6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GroupInfo(BaseModel):
    """One row in the group catalogue."""

    name: str
    description: str = ""
    member_count: int
    members: list[str] = Field(
        ..., description="Portfolio names that belong to this group, sorted."
    )


class GroupDetail(GroupInfo):
    """Currently identical to GroupInfo; reserved for future expansion."""


class CreateGroupRequest(BaseModel):
    """Body for ``POST /groups``.

    Idempotent on the underlying store: re-creating a name updates the
    description without disturbing ``created_at`` or membership.
    """

    name: str = Field(..., min_length=1)
    description: str = ""


class SetMembersRequest(BaseModel):
    """Body for ``PUT /groups/{name}/members``.

    Full replacement of the membership list. The service rejects unknown
    portfolio names with 400 so a typo can't silently desync the group.
    """

    portfolios: list[str]


class SetPortfolioGroupsRequest(BaseModel):
    """Body for ``PUT /portfolios/{name}/groups``.

    Full replacement of the groups a portfolio belongs to. Unknown group
    names are rejected with 400.
    """

    group_names: list[str]

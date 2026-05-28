"""HTTP routes for portfolio groups (slice 6).

Service-layer ValueErrors map to 404/400 via the global handler in
``src.api.errors``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from src.api.deps import data_dir_dep
from src.services import groups as groups_service
from src.services.schemas.group import (
    CreateGroupRequest,
    GroupDetail,
    GroupInfo,
    SetMembersRequest,
)

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("", response_model=list[GroupInfo])
def list_groups(
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> list[GroupInfo]:
    """All groups with their members."""
    return groups_service.list_groups(data_dir)


@router.get("/{name}", response_model=GroupDetail)
def get_group(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> GroupDetail:
    """One group's detail (404 if unknown)."""
    return groups_service.get_group(data_dir, name)


@router.post("", response_model=GroupDetail, status_code=status.HTTP_201_CREATED)
def create_group(
    body: CreateGroupRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> GroupDetail:
    """Create (or update the description of) a group. Idempotent."""
    return groups_service.create_group(data_dir, body.name, description=body.description)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> Response:
    """Delete a group and clear its memberships. 404 if missing."""
    groups_service.delete_group(data_dir, name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{name}/members", response_model=GroupDetail)
def set_members(
    name: str,
    body: SetMembersRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> GroupDetail:
    """Replace the membership list atomically. 400 on unknown portfolios."""
    return groups_service.set_group_members(data_dir, name, body.portfolios)


@router.post("/{name}/members/{portfolio_name}", response_model=GroupDetail)
def add_member(
    name: str,
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> GroupDetail:
    """Add one portfolio to a group. Idempotent. 404 on either side."""
    return groups_service.add_to_group(data_dir, name, portfolio_name)


@router.delete("/{name}/members/{portfolio_name}", response_model=GroupDetail)
def remove_member(
    name: str,
    portfolio_name: str,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> GroupDetail:
    """Remove one portfolio from a group. 404 on missing group."""
    return groups_service.remove_from_group(data_dir, name, portfolio_name)

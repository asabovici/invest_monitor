"""Portfolio-groups service.

Slice 6 of the API refactor — see API_REFACTOR_PLAN.md §5. Wraps the
Database group methods with validation that mirrors the existing CLI
behaviour (e.g. add_to_group rejects unknown group / portfolio names).
"""

from __future__ import annotations

from src.services._db import _get_db
from src.services.schemas.group import GroupDetail, GroupInfo


# ── Catalogue / detail ───────────────────────────────────────────────────────


def list_groups(data_dir: str) -> list[GroupInfo]:
    """All groups with their description, member count, and members."""
    db = _get_db(data_dir)
    out: list[GroupInfo] = []
    for name in db.list_groups():
        members = db.get_group_members(name)
        out.append(GroupInfo(
            name=name,
            description=db.get_group_description(name) or "",
            member_count=len(members),
            members=members,
        ))
    return out


def get_group(data_dir: str, name: str) -> GroupDetail:
    """Return a single group's detail. Raises ``ValueError`` if not found."""
    db = _get_db(data_dir)
    if name not in db.list_groups():
        raise ValueError(f"Group {name!r} not found.")
    members = db.get_group_members(name)
    return GroupDetail(
        name=name,
        description=db.get_group_description(name) or "",
        member_count=len(members),
        members=members,
    )


# ── Group CRUD ───────────────────────────────────────────────────────────────


def create_group(data_dir: str, name: str, description: str = "") -> GroupDetail:
    """Idempotent create: re-creating updates the description only.

    Raises ``ValueError`` for empty names.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Group name is required.")
    db = _get_db(data_dir)
    db.create_group(name, description=description)
    return get_group(data_dir, name)


def delete_group(data_dir: str, name: str) -> None:
    """Delete a group and clear all its memberships.

    Raises ``ValueError`` if the group doesn't exist (the underlying
    parquet update would otherwise silently no-op).
    """
    db = _get_db(data_dir)
    if name not in db.list_groups():
        raise ValueError(f"Group {name!r} does not exist.")
    db.delete_group(name)


# ── Membership ───────────────────────────────────────────────────────────────


def add_to_group(data_dir: str, group_name: str, portfolio_name: str) -> GroupDetail:
    """Add a portfolio to a group. Idempotent.

    Raises ``ValueError`` if either side doesn't exist.
    """
    db = _get_db(data_dir)
    if group_name not in db.list_groups():
        raise ValueError(f"Group {group_name!r} not found.")
    if portfolio_name not in db.list_portfolios():
        raise ValueError(f"Portfolio {portfolio_name!r} not found.")
    db.add_to_group(group_name, portfolio_name)
    return get_group(data_dir, group_name)


def remove_from_group(
    data_dir: str, group_name: str, portfolio_name: str,
) -> GroupDetail:
    """Remove a portfolio from a group. No-op if the pair is absent.

    Raises ``ValueError`` if the group doesn't exist.
    """
    db = _get_db(data_dir)
    if group_name not in db.list_groups():
        raise ValueError(f"Group {group_name!r} not found.")
    db.remove_from_group(group_name, portfolio_name)
    return get_group(data_dir, group_name)


def set_group_members(
    data_dir: str, group_name: str, portfolio_names: list[str],
) -> GroupDetail:
    """Replace the membership list for a group atomically.

    Raises ``ValueError`` if the group is missing or any portfolio name
    is unknown — fail-fast prevents the membership table from desyncing
    on a typo.
    """
    db = _get_db(data_dir)
    if group_name not in db.list_groups():
        raise ValueError(f"Group {group_name!r} not found.")
    valid = set(db.list_portfolios())
    invalid = [p for p in portfolio_names if p not in valid]
    if invalid:
        raise ValueError(f"Unknown portfolios: {invalid!r}")
    db.set_group_members(group_name, portfolio_names)
    return get_group(data_dir, group_name)


def get_groups_for_portfolio(data_dir: str, portfolio_name: str) -> list[str]:
    """All groups containing this portfolio, sorted.

    Raises ``ValueError`` if the portfolio doesn't exist.
    """
    db = _get_db(data_dir)
    if portfolio_name not in db.list_portfolios():
        raise ValueError(f"Portfolio {portfolio_name!r} not found.")
    return db.get_groups_for_portfolio(portfolio_name)


def set_groups_for_portfolio(
    data_dir: str, portfolio_name: str, group_names: list[str],
) -> list[str]:
    """Replace the group memberships for a single portfolio atomically.

    Returns the final list. Raises ``ValueError`` if the portfolio or
    any group is unknown.
    """
    db = _get_db(data_dir)
    if portfolio_name not in db.list_portfolios():
        raise ValueError(f"Portfolio {portfolio_name!r} not found.")
    valid = set(db.list_groups())
    invalid = [g for g in group_names if g not in valid]
    if invalid:
        raise ValueError(f"Unknown groups: {invalid!r}")
    db.set_groups_for_portfolio(portfolio_name, group_names)
    return db.get_groups_for_portfolio(portfolio_name)


__all__ = [
    "list_groups",
    "get_group",
    "create_group",
    "delete_group",
    "add_to_group",
    "remove_from_group",
    "set_group_members",
    "get_groups_for_portfolio",
    "set_groups_for_portfolio",
]

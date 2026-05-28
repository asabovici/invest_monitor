"""Tests for src/services/groups.py."""

import pytest

from src.services.groups import (
    add_to_group,
    create_group,
    delete_group,
    get_group,
    get_groups_for_portfolio,
    list_groups,
    remove_from_group,
    set_group_members,
    set_groups_for_portfolio,
)
from src.services.portfolios import create_portfolio


@pytest.fixture
def data_dir(tmp_path) -> str:
    """Fresh data dir seeded with two portfolios."""
    d = str(tmp_path)
    create_portfolio(d, "P1")
    create_portfolio(d, "P2")
    return d


# ── Create / list / get ──────────────────────────────────────────────────────


def test_create_group_then_list(data_dir: str) -> None:
    detail = create_group(data_dir, "Taxable", description="Brokerage accounts")
    assert detail.name == "Taxable"
    assert detail.description == "Brokerage accounts"
    assert detail.member_count == 0
    names = [g.name for g in list_groups(data_dir)]
    assert "Taxable" in names


def test_create_group_is_idempotent(data_dir: str) -> None:
    create_group(data_dir, "Tax-Free", description="v1")
    detail = create_group(data_dir, "Tax-Free", description="v2")
    assert detail.description == "v2"


def test_create_group_rejects_empty_name(data_dir: str) -> None:
    with pytest.raises(ValueError, match="required"):
        create_group(data_dir, "   ")


def test_get_group_unknown_raises(data_dir: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        get_group(data_dir, "Imaginary")


# ── Membership ───────────────────────────────────────────────────────────────


def test_add_and_remove_member(data_dir: str) -> None:
    create_group(data_dir, "G")
    detail = add_to_group(data_dir, "G", "P1")
    assert detail.members == ["P1"]
    detail = add_to_group(data_dir, "G", "P1")  # idempotent
    assert detail.members == ["P1"]
    detail = remove_from_group(data_dir, "G", "P1")
    assert detail.members == []


def test_add_member_unknown_group_raises(data_dir: str) -> None:
    with pytest.raises(ValueError, match="Group"):
        add_to_group(data_dir, "Imaginary", "P1")


def test_add_member_unknown_portfolio_raises(data_dir: str) -> None:
    create_group(data_dir, "G")
    with pytest.raises(ValueError, match="Portfolio"):
        add_to_group(data_dir, "G", "no-such")


def test_set_group_members_replaces_atomically(data_dir: str) -> None:
    create_group(data_dir, "G")
    add_to_group(data_dir, "G", "P1")
    detail = set_group_members(data_dir, "G", ["P2"])
    assert detail.members == ["P2"]


def test_set_group_members_rejects_unknown_portfolios(data_dir: str) -> None:
    create_group(data_dir, "G")
    with pytest.raises(ValueError, match="Unknown portfolios"):
        set_group_members(data_dir, "G", ["P1", "Ghost"])


# ── Delete ───────────────────────────────────────────────────────────────────


def test_delete_group(data_dir: str) -> None:
    create_group(data_dir, "Goner")
    delete_group(data_dir, "Goner")
    assert "Goner" not in [g.name for g in list_groups(data_dir)]


def test_delete_unknown_group_raises(data_dir: str) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        delete_group(data_dir, "Imaginary")


# ── Portfolio-side helpers ───────────────────────────────────────────────────


def test_get_and_set_groups_for_portfolio(data_dir: str) -> None:
    create_group(data_dir, "A")
    create_group(data_dir, "B")
    set_groups_for_portfolio(data_dir, "P1", ["A", "B"])
    assert get_groups_for_portfolio(data_dir, "P1") == ["A", "B"]
    set_groups_for_portfolio(data_dir, "P1", [])
    assert get_groups_for_portfolio(data_dir, "P1") == []


def test_get_groups_for_unknown_portfolio_raises(data_dir: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        get_groups_for_portfolio(data_dir, "no-such")


def test_set_groups_for_portfolio_rejects_unknown_group(data_dir: str) -> None:
    with pytest.raises(ValueError, match="Unknown groups"):
        set_groups_for_portfolio(data_dir, "P1", ["Imaginary"])

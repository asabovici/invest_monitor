"""Tests for src/services/portfolios.py against the demo dataset."""

import pytest

from src.services.portfolios import (
    get_portfolio,
    list_portfolio_names,
    list_portfolios,
)

DEMO = "data_demo"


def test_list_portfolio_names_returns_demo_names() -> None:
    names = list_portfolio_names(DEMO)
    assert isinstance(names, list)
    assert all(isinstance(n, str) for n in names)
    # The demo seed creates these portfolios; assert they're present rather
    # than asserting exact length (so the test survives seed changes).
    for expected in ("Demo Cash & CDs", "Demo Retirement", "Demo Brokerage"):
        assert expected in names, f"missing expected demo portfolio: {expected}"


def test_list_portfolios_returns_summaries_with_counts_and_cost() -> None:
    summaries = list_portfolios(DEMO)
    assert summaries, "expected at least one demo portfolio"
    by_name = {s.name: s for s in summaries}
    cash_cd = by_name["Demo Cash & CDs"]
    assert cash_cd.position_count >= 1
    assert cash_cd.total_cost > 0


def test_get_portfolio_returns_detail_with_positions() -> None:
    detail = get_portfolio(DEMO, "Demo Brokerage")
    assert detail.name == "Demo Brokerage"
    assert detail.positions, "Demo Brokerage should have positions"
    pos = detail.positions[0]
    assert pos.ticker
    assert pos.quantity > 0
    # Cost basis is per share, not total — see CLAUDE memory.
    assert pos.cost_basis_per_share > 0
    # total_cost agrees with sum of positions.
    rolled = sum(p.quantity * p.cost_basis_per_share for p in detail.positions)
    assert detail.total_cost == pytest.approx(rolled, rel=1e-6)


def test_get_portfolio_raises_value_error_on_missing() -> None:
    with pytest.raises(ValueError):
        get_portfolio(DEMO, "does-not-exist-xyz")

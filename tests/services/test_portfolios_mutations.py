"""Tests for portfolio mutation services (slice 2)."""

import pytest

from src.api.schemas.portfolio import PositionInput
from src.services.portfolios import (
    create_portfolio,
    delete_portfolio,
    get_portfolio,
    list_portfolio_names,
    load_portfolio_from_csv,
    update_positions,
)


# ── create / delete ──────────────────────────────────────────────────────────


def test_create_portfolio_creates_empty(tmp_path) -> None:
    data_dir = str(tmp_path)
    detail = create_portfolio(data_dir, "Test PF")
    assert detail.name == "Test PF"
    assert detail.positions == []
    assert detail.total_cost == 0
    assert "Test PF" in list_portfolio_names(data_dir)


def test_create_portfolio_raises_on_duplicate(tmp_path) -> None:
    data_dir = str(tmp_path)
    create_portfolio(data_dir, "Dup")
    with pytest.raises(ValueError, match="already exists"):
        create_portfolio(data_dir, "Dup")


def test_create_portfolio_raises_on_empty_name(tmp_path) -> None:
    with pytest.raises(ValueError, match="required"):
        create_portfolio(str(tmp_path), "   ")


def test_delete_portfolio_removes_it(tmp_path) -> None:
    data_dir = str(tmp_path)
    create_portfolio(data_dir, "Goner")
    delete_portfolio(data_dir, "Goner")
    assert "Goner" not in list_portfolio_names(data_dir)


def test_delete_portfolio_raises_on_missing(tmp_path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        delete_portfolio(str(tmp_path), "never-was")


# ── load_portfolio_from_csv ──────────────────────────────────────────────────


_SAMPLE_CSV = """Ticker,Name,Type,Quantity,CostBasis,Currency,Sector
AAPL,Apple Inc,Stock,10,1500,USD,Technology
BND,Vanguard Total Bond,ETF,50,4000,USD,Fixed Income
"""


def test_load_portfolio_from_csv_creates_with_positions(tmp_path) -> None:
    data_dir = str(tmp_path)
    detail = load_portfolio_from_csv(data_dir, "From CSV", _SAMPLE_CSV)
    assert detail.name == "From CSV"
    tickers = {p.ticker for p in detail.positions}
    assert tickers == {"AAPL", "BND"}
    aapl = next(p for p in detail.positions if p.ticker == "AAPL")
    # CostBasis 1500 over 10 shares → per-share 150
    assert aapl.cost_basis_per_share == pytest.approx(150.0)
    assert aapl.asset_type == "Stock"
    assert aapl.sector == "Technology"


def test_load_portfolio_from_csv_replaces_existing(tmp_path) -> None:
    data_dir = str(tmp_path)
    load_portfolio_from_csv(data_dir, "Twice", _SAMPLE_CSV)
    smaller_csv = "Ticker,Name,Type,Quantity,CostBasis,Currency,Sector\nAAPL,Apple,Stock,1,200,USD,Technology\n"
    detail = load_portfolio_from_csv(data_dir, "Twice", smaller_csv)
    assert [p.ticker for p in detail.positions] == ["AAPL"]


def test_load_portfolio_from_csv_rejects_empty(tmp_path) -> None:
    with pytest.raises(ValueError, match="empty"):
        load_portfolio_from_csv(str(tmp_path), "Bad", "   ")


# ── update_positions ─────────────────────────────────────────────────────────


def test_update_positions_replaces_all(tmp_path) -> None:
    data_dir = str(tmp_path)
    create_portfolio(data_dir, "Holdings")
    update_positions(
        data_dir,
        "Holdings",
        [
            PositionInput(
                ticker="VTI", quantity=10, cost_basis_per_share=200.0,
                asset_type="ETF", name="Vanguard Total Market",
            ),
            PositionInput(
                ticker="BND", quantity=5, cost_basis_per_share=80.0,
                asset_type="ETF", name="Vanguard Total Bond",
            ),
        ],
    )
    detail = get_portfolio(data_dir, "Holdings")
    assert {p.ticker for p in detail.positions} == {"VTI", "BND"}
    assert detail.total_cost == pytest.approx(10 * 200.0 + 5 * 80.0)


def test_update_positions_empty_list_clears_portfolio(tmp_path) -> None:
    data_dir = str(tmp_path)
    create_portfolio(data_dir, "Empty Me")
    update_positions(
        data_dir, "Empty Me",
        [PositionInput(ticker="VTI", quantity=1, cost_basis_per_share=100.0, asset_type="ETF")],
    )
    update_positions(data_dir, "Empty Me", [])
    detail = get_portfolio(data_dir, "Empty Me")
    assert detail.positions == []


def test_update_positions_raises_on_missing_portfolio(tmp_path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        update_positions(str(tmp_path), "never-created", [])


def test_update_positions_rejects_invalid_asset_type(tmp_path) -> None:
    data_dir = str(tmp_path)
    create_portfolio(data_dir, "X")
    with pytest.raises(ValueError, match="Invalid asset_type"):
        update_positions(
            data_dir, "X",
            [PositionInput(
                ticker="WAT", quantity=1, cost_basis_per_share=1.0,
                asset_type="Banana",  # not in AssetType
            )],
        )

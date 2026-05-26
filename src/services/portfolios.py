"""Portfolio service: read + write paths.

Slices 1 (reads) and 2 (mutations) of the API refactor — see
API_REFACTOR_PLAN.md §5.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.api.schemas.portfolio import (
    LoadCsvRequest,
    PortfolioDetail,
    PortfolioSummary,
    PositionInput,
    PositionView,
)
from src.data.ingestion import Ingester
from src.database import Database
from src.models import Asset, AssetType, Portfolio, Position


def _to_position_view(pos) -> PositionView:
    return PositionView(
        ticker=pos.asset.ticker,
        asset_type=pos.asset.asset_type.value,
        name=pos.asset.name,
        sector=pos.asset.sector,
        currency=pos.asset.currency,
        quantity=float(pos.quantity),
        cost_basis_per_share=float(pos.cost_basis),
    )


def _to_summary(portfolio: Portfolio) -> PortfolioSummary:
    return PortfolioSummary(
        name=portfolio.name,
        position_count=len(portfolio.positions),
        total_cost=portfolio.total_cost(),
    )


def list_portfolio_names(data_dir: str) -> list[str]:
    """Cheap names-only listing — no position load, no cost roll-up.

    Use this in internal callers that only need the list of names (dashboard
    selectors, membership checks). API responses prefer ``list_portfolios``,
    which adds position count and total cost.
    """
    return Database(data_dir).list_portfolios()


def list_portfolios(data_dir: str) -> list[PortfolioSummary]:
    """Return one summary per saved portfolio, newest-first by creation."""
    db = Database(data_dir)
    names = db.list_portfolios()
    return [_to_summary(db.get_portfolio(name)) for name in names]


def get_portfolio(data_dir: str, name: str) -> PortfolioDetail:
    """Return the full portfolio with positions, or raise ``ValueError`` if missing.

    Raises:
        ValueError: portfolio ``name`` does not exist in ``data_dir``.
    """
    db = Database(data_dir)
    portfolio = db.get_portfolio(name)  # raises ValueError on unknown name
    return _detail_from_portfolio(portfolio)


def _detail_from_portfolio(portfolio: Portfolio) -> PortfolioDetail:
    return PortfolioDetail(
        name=portfolio.name,
        positions=[_to_position_view(p) for p in portfolio.positions],
        total_cost=portfolio.total_cost(),
    )


# ── Mutations ──────────────────────────────────────────────────────────────────


def create_portfolio(data_dir: str, name: str) -> PortfolioDetail:
    """Create an empty portfolio.

    Raises:
        ValueError: ``name`` is empty or a portfolio with that name already exists.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Portfolio name is required.")
    db = Database(data_dir)
    if name in db.list_portfolios():
        raise ValueError(f"Portfolio '{name}' already exists.")
    db.save_portfolio(Portfolio(name=name, positions=[]))
    return _detail_from_portfolio(db.get_portfolio(name))


def delete_portfolio(data_dir: str, name: str) -> None:
    """Delete a portfolio.

    Raises:
        ValueError: ``name`` does not exist in ``data_dir``.
    """
    db = Database(data_dir)
    if name not in db.list_portfolios():
        raise ValueError(f"Portfolio '{name}' does not exist.")
    db.delete_portfolio(name)


def load_portfolio_from_csv(
    data_dir: str, name: str, csv_text: str
) -> PortfolioDetail:
    """Import positions from CSV text and upsert them into ``name``.

    Upserts both the portfolio and any new assets. If the portfolio
    already exists, its positions are replaced (matches the existing
    ``Ingester`` behaviour).

    Raises:
        ValueError: ``name`` or ``csv_text`` is empty.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Portfolio name is required.")
    if not (csv_text or "").strip():
        raise ValueError("csv_text is empty.")

    db = Database(data_dir)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(csv_text)
        tmp_path = tmp.name
    try:
        Ingester(db).load_portfolio_from_csv(tmp_path, name)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return _detail_from_portfolio(db.get_portfolio(name))


def update_positions(
    data_dir: str, name: str, positions: list[PositionInput]
) -> PortfolioDetail:
    """Replace all positions for ``name`` with ``positions`` (PUT semantics).

    For each position, the corresponding asset row is upserted before the
    position is saved so the assets table stays in sync. An empty list
    clears the portfolio.

    Raises:
        ValueError: ``name`` does not exist in ``data_dir``, or an
            ``asset_type`` value is not a member of ``AssetType``.
    """
    db = Database(data_dir)
    if name not in db.list_portfolios():
        raise ValueError(f"Portfolio '{name}' does not exist.")

    rebuilt_positions: list[Position] = []
    for p in positions:
        try:
            asset_type = AssetType(p.asset_type)
        except ValueError as exc:
            raise ValueError(
                f"Invalid asset_type '{p.asset_type}' for ticker '{p.ticker}'."
            ) from exc
        asset = Asset(
            ticker=p.ticker,
            asset_type=asset_type,
            name=p.name or p.ticker,
            sector=p.sector,
            currency=p.currency,
        )
        db.add_asset(asset)
        rebuilt_positions.append(
            Position(asset=asset, quantity=p.quantity, cost_basis=p.cost_basis_per_share)
        )

    db.save_portfolio(Portfolio(name=name, positions=rebuilt_positions))
    return _detail_from_portfolio(db.get_portfolio(name))


__all__ = [
    "list_portfolio_names",
    "list_portfolios",
    "get_portfolio",
    "create_portfolio",
    "delete_portfolio",
    "load_portfolio_from_csv",
    "update_positions",
]

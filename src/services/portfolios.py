"""Portfolio read-side service functions.

Slice 1 of the API refactor (see API_REFACTOR_PLAN.md §5): read paths
only. Mutations (create, delete, update positions) land in slice 2.
"""

from __future__ import annotations

from src.api.schemas.portfolio import PortfolioDetail, PortfolioSummary, PositionView
from src.database import Database
from src.models import Portfolio


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
    return PortfolioDetail(
        name=portfolio.name,
        positions=[_to_position_view(p) for p in portfolio.positions],
        total_cost=portfolio.total_cost(),
    )

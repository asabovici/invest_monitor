"""Trades service: ledger reads + recording new trades.

Slice 6 of the API refactor — see API_REFACTOR_PLAN.md §5. The trade
ledger is append-only; positions are derived by ``Database.record_trade``
applying average-cost blending on BUY and FIFO-style reduction on SELL.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.services._db import _get_db
from src.services.schemas.trade import RecordTradeRequest, TradeList, TradeRow


# ── Reads ────────────────────────────────────────────────────────────────────


def list_trades(data_dir: str, portfolio_name: str | None = None) -> TradeList:
    """All trades, optionally filtered by portfolio. Newest first.

    Raises ``ValueError`` if ``portfolio_name`` is given but missing.
    """
    db = _get_db(data_dir)
    if portfolio_name is not None and portfolio_name not in db.list_portfolios():
        raise ValueError(f"Portfolio {portfolio_name!r} not found.")
    df = db.list_trades(portfolio_name=portfolio_name)
    rows = [_row_to_schema(r) for _, r in df.iterrows()] if not df.empty else []
    return TradeList(trades=rows)


def _row_to_schema(row) -> TradeRow:
    return TradeRow(
        trade_id=int(row["trade_id"]),
        portfolio_name=str(row["portfolio_name"]),
        ticker=str(row["ticker"]),
        side=str(row["side"]),  # type: ignore[arg-type]  # Literal validated by pydantic
        quantity=float(row["quantity"]),
        trade_price=float(row["trade_price"]),
        trade_date=pd.Timestamp(row["trade_date"]).date(),
    )


# ── Writes ───────────────────────────────────────────────────────────────────


def record_trade(data_dir: str, body: RecordTradeRequest) -> TradeList:
    """Append a trade to the ledger and apply it to positions.

    Returns the updated trade list for ``body.portfolio_name`` so callers
    can refresh their view in a single round-trip.

    Raises:
        ValueError: portfolio not found.
    """
    db = _get_db(data_dir)
    if body.portfolio_name not in db.list_portfolios():
        raise ValueError(f"Portfolio {body.portfolio_name!r} not found.")
    db.record_trade(
        portfolio_name=body.portfolio_name,
        ticker=body.ticker,
        side=body.side,
        quantity=float(body.quantity),
        trade_price=float(body.trade_price),
        trade_date=body.trade_date.isoformat(),
    )
    return list_trades(data_dir, portfolio_name=body.portfolio_name)


__all__ = ["list_trades", "record_trade"]

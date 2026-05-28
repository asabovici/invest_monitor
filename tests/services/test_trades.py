"""Tests for src/services/trades.py."""

from datetime import date

import pytest

from src.services.portfolios import create_portfolio
from src.services.schemas.trade import RecordTradeRequest
from src.services.trades import list_trades, record_trade


@pytest.fixture
def data_dir(tmp_path) -> str:
    d = str(tmp_path)
    create_portfolio(d, "P1")
    return d


def test_list_trades_empty(data_dir: str) -> None:
    assert list_trades(data_dir).trades == []
    assert list_trades(data_dir, portfolio_name="P1").trades == []


def test_record_trade_persists_and_returns_list(data_dir: str) -> None:
    result = record_trade(data_dir, RecordTradeRequest(
        portfolio_name="P1", ticker="AAPL", side="BUY",
        quantity=10, trade_price=150, trade_date=date(2026, 5, 1),
    ))
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.ticker == "AAPL"
    assert t.quantity == 10
    assert t.side == "BUY"


def test_record_trade_unknown_portfolio_raises(data_dir: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        record_trade(data_dir, RecordTradeRequest(
            portfolio_name="no-such", ticker="AAPL", side="BUY",
            quantity=1, trade_price=1, trade_date=date(2026, 5, 1),
        ))


def test_list_trades_unknown_portfolio_raises(data_dir: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        list_trades(data_dir, portfolio_name="no-such")


def test_record_trade_invalid_side_caught_by_schema() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError
        RecordTradeRequest(
            portfolio_name="P1", ticker="AAPL", side="HOLD",
            quantity=1, trade_price=1, trade_date=date(2026, 5, 1),
        )


def test_record_trade_negative_quantity_caught_by_schema() -> None:
    with pytest.raises(Exception):
        RecordTradeRequest(
            portfolio_name="P1", ticker="AAPL", side="BUY",
            quantity=-1, trade_price=1, trade_date=date(2026, 5, 1),
        )

"""Prices service: latest, history, and yfinance-driven collection.

Slice 3 of the API refactor — see API_REFACTOR_PLAN.md §5.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Iterable

import pandas as pd

if TYPE_CHECKING:
    from src.database import Database

from src.services.schemas.price import (
    CollectionResult,
    LatestPriceResponse,
    PriceHistory,
)
from src.services._db import _get_db


# ── Reads ──────────────────────────────────────────────────────────────────────


def get_latest_prices(data_dir: str, tickers: Iterable[str]) -> LatestPriceResponse:
    """Return the latest stored close price for each ticker.

    Tickers with no price history map to ``None`` (so a missing series can
    be distinguished from a real zero). Cash / CD synthetic prices (1.0)
    are surfaced as 1.0 — they're considered "data" by the data layer.
    """
    tickers = list(tickers)
    if not tickers:
        return LatestPriceResponse(prices={})

    df = _get_db(data_dir).get_historical_prices(tickers)
    latest: dict[str, float | None] = {}
    for t in tickers:
        if df.empty or t not in df.columns:
            latest[t] = None
            continue
        series = df[t].dropna()
        latest[t] = float(series.iloc[-1]) if not series.empty else None
    return LatestPriceResponse(prices=latest)


def get_price_history(
    data_dir: str,
    tickers: Iterable[str],
    start: date | str | None = None,
) -> PriceHistory:
    """Aligned-date price history for ``tickers``.

    ``start`` accepts a ``date`` or ISO-format string. Missing samples
    become ``None`` so the response is rebuildable into a DataFrame
    without re-aligning indexes.
    """
    tickers = list(tickers)
    start_str = start.isoformat() if isinstance(start, date) else start

    df = _get_db(data_dir).get_historical_prices(tickers, start_date=start_str)
    if df.empty:
        return PriceHistory(tickers=tickers, dates=[], prices={t: [] for t in tickers})

    # Normalise to date (drop time-of-day) and ensure ascending order.
    df = df.sort_index()
    dates = [d.date() if hasattr(d, "date") else pd.to_datetime(d).date() for d in df.index]
    prices: dict[str, list[float | None]] = {}
    for t in tickers:
        if t in df.columns:
            prices[t] = [None if pd.isna(v) else float(v) for v in df[t].tolist()]
        else:
            prices[t] = [None] * len(dates)
    return PriceHistory(tickers=tickers, dates=dates, prices=prices)


def price_history_to_dataframe(history: PriceHistory) -> pd.DataFrame:
    """Reconstruct a ``DataFrame`` (date index, ticker columns) from a ``PriceHistory``.

    For in-process callers (Streamlit) that still want a DataFrame.
    Out-of-process clients should consume the JSON shape directly.
    """
    if not history.dates:
        return pd.DataFrame(columns=history.tickers)
    idx = pd.DatetimeIndex(history.dates)
    return pd.DataFrame(history.prices, index=idx)


# ── Writes ─────────────────────────────────────────────────────────────────────


def collect_prices(
    data_dir: str,
    period: str = "1y",
    portfolio_name: str | None = None,
) -> CollectionResult:
    """Fetch prices via yfinance and save to the database.

    Without ``portfolio_name``: collect every asset in the assets table.
    With ``portfolio_name``: collect only that portfolio's tickers.

    Failures (yfinance error, empty response) land in ``tickers_failed``
    rather than raising — bulk collection should not abort on one bad
    ticker.
    """
    db = _get_db(data_dir)
    if portfolio_name:
        portfolio = db.get_portfolio(portfolio_name)  # raises ValueError if missing
        tickers = [pos.asset.ticker for pos in portfolio.positions]
    else:
        tickers = db.get_all_tickers()

    if not tickers:
        return CollectionResult(tickers_collected=[], tickers_failed={})

    return _collect_for_tickers(db, tickers, period)


def _collect_for_tickers(db: Database, tickers: list[str], period: str) -> CollectionResult:
    """Per-ticker fetch + save, gathering errors instead of aborting."""
    import yfinance as yf

    collected: list[str] = []
    failed: dict[str, str] = {}
    for ticker in tickers:
        try:
            data = yf.download(ticker, period=period, progress=False)
        except Exception as exc:  # noqa: BLE001 — yfinance can raise opaque exceptions
            failed[ticker] = f"download error: {exc}"
            continue
        if data is None or data.empty:
            failed[ticker] = "no data returned"
            continue
        try:
            db.save_prices(ticker, data)
        except Exception as exc:  # noqa: BLE001
            failed[ticker] = f"save error: {exc}"
            continue
        collected.append(ticker)
    return CollectionResult(tickers_collected=collected, tickers_failed=failed)


__all__ = [
    "get_latest_prices",
    "get_price_history",
    "price_history_to_dataframe",
    "collect_prices",
]

"""Dashboard snapshot service — one aggregate payload per screen load.

Why this exists rather than composing on the client: the Dashboard needs a
value-over-time series across every holding, and building that from
``/prices/history`` would take one request per ticker. Aggregating here
turns a page load into a single round trip.

Two data realities shape the implementation, both discovered against the
live dataset:

1. **``daily_portfolio_metrics`` is not usable as a net-worth series.**
   Coverage is ragged — a given date may have rows for only some
   portfolios — so summing by date produces cliffs where an account simply
   has no row that day (observed: an apparent -81% drop in one session).
   This module therefore values *current holdings at historical prices*
   instead, which is well-defined for every date in the price history.

2. **The resulting series is a constant-holdings backtest**, not a record
   of past balances. Positions carry no time dimension, so real historical
   balances aren't reconstructable from them. Clients must label it as
   such; see :class:`ValueSeries`.
"""

from __future__ import annotations

import os
from functools import lru_cache

import pandas as pd

from src.services._db import _get_db
from src.services.schemas.dashboard import DashboardSnapshot, Holding, ValueSeries

# Cash and CDs are held at par and have no price file by design.
_PAR_TYPES = {"Cash", "CD"}
_DEFAULT_START = "2021-05-14"
_FREQ = "W-FRI"


def _price_history(data_dir: str, ticker: str) -> pd.Series | None:
    path = os.path.join(data_dir, "prices", f"{ticker}.parquet")
    if not os.path.exists(path):
        return None
    try:
        s = pd.read_parquet(path)["price"].dropna()
    except (KeyError, OSError, ValueError):
        return None
    if s.empty:
        return None
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _resample(s: pd.Series | None, index: pd.DatetimeIndex, latest: float) -> pd.Series:
    """Align a price series to ``index``, pinning the final point to ``latest``.

    Without the pin the last sample is whatever the weekly resample landed
    on, so headline "today" figures would disagree with the end of the
    chart by a few days of drift.
    """
    if s is None:
        out = pd.Series(latest, index=index)
    else:
        out = s.reindex(index.union(s.index)).ffill().reindex(index).bfill()
    out = out.copy()
    out.iloc[-1] = latest
    return out


def get_snapshot(
    data_dir: str, start: str = _DEFAULT_START, portfolio: str | None = None
) -> DashboardSnapshot:
    """Aggregate everything the Dashboard screen renders.

    Holdings with no price and no par convention are excluded from totals
    and reported in ``unpriced`` rather than silently valued at zero.

    ``portfolio`` scopes the snapshot to one account; ``None`` spans every
    portfolio. Validation is against the portfolio list rather than the
    positions, so a real-but-empty portfolio returns an empty snapshot
    instead of being reported as missing.

    Raises:
        ValueError: ``portfolio`` names a portfolio that does not exist.
    """
    db = _get_db(data_dir)
    positions = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    if portfolio is not None:
        if portfolio not in db.list_portfolios():
            raise ValueError(f"Portfolio {portfolio!r} not found.")
        positions = positions[positions["portfolio_name"] == portfolio]
    assets = db.get_all_assets().set_index("ticker")
    types = assets["asset_type"] if "asset_type" in assets.columns else pd.Series(dtype=str)
    names = assets["name"] if "name" in assets.columns else pd.Series(dtype=str)

    index = pd.date_range(start, pd.Timestamp.today().normalize(), freq=_FREQ)
    if len(index) < 2:
        raise ValueError(f"Start date {start!r} leaves too little history to plot.")

    order = ["Cash", "Bond", "Fund", "ETF", "Stock"]
    by_type = {t: pd.Series(0.0, index=index) for t in order}
    holdings: list[Holding] = []
    unpriced: list[str] = []

    for _, row in positions.iterrows():
        ticker = str(row["ticker"])
        atype = str(types.get(ticker, "Stock"))
        bucket = atype if atype in by_type else "Stock"

        series = _price_history(data_dir, ticker)
        if series is None:
            if atype not in _PAR_TYPES:
                unpriced.append(ticker)
                continue
            latest = 1.0
        else:
            latest = float(series.iloc[-1])

        qty = float(row["quantity"])
        by_type[bucket] = by_type[bucket].add(
            _resample(series, index, latest) * qty, fill_value=0.0
        )
        holdings.append(Holding(
            ticker=ticker,
            name=str(names.get(ticker, "") or "").strip() or ticker,
            account=str(row["portfolio_name"]),
            asset_type=bucket,
            quantity=qty,
            price=latest,
            market_value=qty * latest,
            cost=qty * float(row["cost_basis"]),
        ))

    holdings.sort(key=lambda h: h.market_value, reverse=True)
    total = sum(by_type.values())

    by_account: dict[str, float] = {}
    for h in holdings:
        by_account[h.account] = by_account.get(h.account, 0.0) + h.market_value

    market_value = sum(h.market_value for h in holdings)
    cost = sum(h.cost for h in holdings)

    return DashboardSnapshot(
        market_value=round(market_value, 2),
        cost=round(cost, 2),
        gain=round(market_value - cost, 2),
        asset_type_order=order,
        totals_by_type={t: round(float(v.iloc[-1]), 2) for t, v in by_type.items()},
        totals_by_account=dict(
            sorted(((k, round(v, 2)) for k, v in by_account.items()), key=lambda kv: -kv[1])
        ),
        series=ValueSeries(
            dates=[d.strftime("%Y-%m-%d") for d in index],
            total=[round(float(v), 2) for v in total],
            by_type={t: [round(float(x), 2) for x in v] for t, v in by_type.items()},
        ),
        holdings=holdings,
        unpriced=sorted(unpriced),
    )


__all__ = ["get_snapshot"]

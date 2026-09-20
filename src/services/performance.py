"""Rebased price history for the Performance screen.

Returns cumulative return rather than raw price so series of wildly
different unit prices are comparable on one axis — a $600 share and a $30
share are the same line shape when both start at 0.

Holdings are valued from the snapshot, so the portfolio blend is weighted
by what is actually held rather than equally per ticker.
"""

from __future__ import annotations

import os

import pandas as pd

from src.services.schemas.performance import PerformanceReport, TickerSeries

# Cash and CDs are held at par — a flat line at 0% is noise on a return chart.
_PAR_TYPES = {"Cash", "CD"}


def _history(data_dir: str, ticker: str) -> pd.Series | None:
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


def get_performance(
    data_dir: str, portfolio: str | None = None, start: str | None = None
) -> PerformanceReport:
    """Cumulative return per holding, plus the value-weighted blend.

    ``portfolio`` scopes to one account; ``None`` spans every portfolio.
    ``start`` trims the window; ``None`` uses all available history.

    Raises:
        ValueError: unknown ``portfolio``, or no holding has price history.
    """
    from src.services.dashboard import get_snapshot

    snap = get_snapshot(data_dir, portfolio=portfolio)

    frames: dict[str, pd.Series] = {}
    excluded: list[str] = []
    weights: dict[str, float] = {}
    types: dict[str, str] = {}

    for h in snap.holdings:
        if h.asset_type in _PAR_TYPES:
            excluded.append(h.ticker)
            continue
        if h.ticker not in frames:
            s = _history(data_dir, h.ticker)
            if s is None or len(s) < 2:
                excluded.append(h.ticker)
                continue
            frames[h.ticker] = s
            types[h.ticker] = h.asset_type
        # The same ticker can be held in several accounts; under an
        # unscoped report those rows are one line with the summed value.
        weights[h.ticker] = weights.get(h.ticker, 0.0) + h.market_value

    if not frames:
        raise ValueError("No holdings with usable price history — nothing to plot.")

    prices = pd.DataFrame(frames).sort_index()
    if start:
        prices = prices[prices.index >= pd.Timestamp(start)]
    if len(prices) < 2:
        raise ValueError(f"Start date {start!r} leaves too little history to plot.")

    # Rebase each column to its own first observation, not the window's first
    # row — a ticker that starts mid-window must still begin at 0%.
    first = prices.apply(lambda c: c.dropna().iloc[0] if not c.dropna().empty else float("nan"))
    rebased = prices.div(first) - 1.0

    total_weight = sum(weights.values()) or 1.0
    w = pd.Series({t: v / total_weight for t, v in weights.items()})
    # dropna(how="any") because a dot product propagates NaN: one missing
    # sample would blank the whole blended series for that date.
    aligned = rebased.dropna(how="any")
    if aligned.empty:
        blend = pd.Series(index=rebased.index, dtype=float)
    else:
        blend = aligned.dot(w.reindex(aligned.columns).fillna(0.0)).reindex(rebased.index)

    def _col(values) -> list[float | None]:
        return [None if pd.isna(v) else round(float(v), 6) for v in values]

    series = [
        TickerSeries(
            ticker=t,
            asset_type=types[t],
            market_value=round(weights[t], 2),
            cumulative_return=_col(rebased[t]),
            total_return=round(float(rebased[t].dropna().iloc[-1]), 6),
        )
        for t in rebased.columns
    ]
    series.sort(key=lambda s: s.market_value, reverse=True)

    blend_list = _col(blend)
    last_blend = next((v for v in reversed(blend_list) if v is not None), 0.0)

    return PerformanceReport(
        dates=[d.strftime("%Y-%m-%d") for d in rebased.index],
        series=series,
        portfolio_cumulative_return=blend_list,
        portfolio_total_return=round(float(last_blend), 6),
        excluded=sorted(set(excluded)),
    )


__all__ = ["get_performance"]

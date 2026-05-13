"""Daily returns, risk, and performance-attribution metrics.

Computes long-format DataFrames suitable for persisting to parquet so that we
have a queryable time series of how each portfolio (and each holding within
it) performed day by day.

Two reconstruction modes (chosen automatically per portfolio):

* **Trade replay (v2)** — when `trades.parquet` has any rows for the
  portfolio, positions are materialised by cumulative-summing trade
  quantities (BUY +, SELL −) per ticker. Each historical date uses the
  *actual* holdings on that date. Quantities before the first trade are 0.

* **Static current (v1)** — fallback when no trades are recorded. Uses
  today's positions across the whole price history. Answers "if I had
  held this portfolio over time …" rather than "what did I actually hold".
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from src.database import Database
from src.models import Portfolio


class AttributionEngine:
    def __init__(self, db: Database):
        self.db = db

    # ── Security-level (price-only, position-agnostic) ────────────────────────

    def compute_security_metrics(
        self,
        tickers: Optional[list[str]] = None,
        start_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Per-ticker daily metrics: price, daily return, cumulative return, 21d vol.

        Cumulative return is anchored at the first valid date in the fetched
        window — recomputed on every refresh so the series stays self-consistent.
        """
        if tickers is None:
            tickers = self.db.get_all_tickers()
        if not tickers:
            return pd.DataFrame(columns=[
                "date", "ticker", "price", "daily_return", "cum_return", "rolling_vol_21d",
            ])

        prices = self.db.get_historical_prices(tickers, start_date=start_date)
        if prices.empty:
            return pd.DataFrame(columns=[
                "date", "ticker", "price", "daily_return", "cum_return", "rolling_vol_21d",
            ])

        prices = prices.sort_index()
        rets = prices.pct_change()
        cum  = (1.0 + rets.fillna(0.0)).cumprod() - 1.0
        # Mask cumulative-return values before each ticker's first valid price
        # so we don't pretend the position existed on those dates.
        first_valid = prices.apply(lambda col: col.first_valid_index())
        for ticker in prices.columns:
            fv = first_valid[ticker]
            if fv is not None:
                cum.loc[cum.index < fv, ticker] = np.nan
        vol21 = rets.rolling(21).std() * np.sqrt(252.0)

        frames = []
        for ticker in prices.columns:
            df = pd.DataFrame({
                "date":            prices.index,
                "ticker":          ticker,
                "price":           prices[ticker].values,
                "daily_return":    rets[ticker].values,
                "cum_return":      cum[ticker].values,
                "rolling_vol_21d": vol21[ticker].values,
            })
            # Drop rows where the ticker has no price on that date.
            df = df.dropna(subset=["price"]).reset_index(drop=True)
            frames.append(df)

        result = pd.concat(frames, ignore_index=True)
        result["date"] = pd.to_datetime(result["date"])
        return result

    # ── Portfolio-level + attribution (uses current static positions) ─────────

    def compute_portfolio_history(
        self,
        portfolio: Portfolio,
        start_date: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Return (daily_portfolio_metrics_df, daily_attribution_df) for one portfolio.

        Daily return at t = Σᵢ (wᵢ at t-1) × (return of i at t), so the sum of
        per-position contributions equals the portfolio return on each day —
        the standard Brinson decomposition.
        """
        empty_port = pd.DataFrame(columns=[
            "date", "portfolio_name", "total_value", "daily_return",
            "cum_return", "rolling_vol_21d", "drawdown", "max_drawdown",
        ])
        empty_attr = pd.DataFrame(columns=[
            "date", "portfolio_name", "ticker", "weight",
            "position_return", "contribution_to_return", "asset_type", "sector",
        ])

        if not portfolio.positions:
            return empty_port, empty_attr

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        pos_by_t = {pos.asset.ticker: pos for pos in portfolio.positions}

        prices = self.db.get_historical_prices(tickers, start_date=start_date)
        if prices.empty:
            return empty_port, empty_attr
        prices = prices.sort_index()

        # Per-position $ value at each date (qty × price). NaN if no price.
        position_values = pd.DataFrame(
            {t: pos_by_t[t].quantity * prices[t] for t in tickers if t in prices.columns}
        )
        if position_values.empty:
            return empty_port, empty_attr

        total_value = position_values.sum(axis=1, min_count=1)
        # Weights at each date (renormalises to available positions that day).
        weights = position_values.div(total_value, axis=0)
        # Yesterday's weights × today's returns = today's attribution.
        prev_weights = weights.shift(1)
        rets = prices[position_values.columns].pct_change()
        contributions = prev_weights * rets
        port_return = contributions.sum(axis=1, min_count=1)

        cumulative = (1.0 + port_return.fillna(0.0)).cumprod()
        # Mask cumulative-return before the first date the portfolio had any value.
        first_valid_total = total_value.first_valid_index()
        if first_valid_total is not None:
            cumulative.loc[cumulative.index < first_valid_total] = np.nan
        cum_return = cumulative - 1.0
        cummax = cumulative.cummax()
        drawdown = (cumulative - cummax) / cummax
        max_drawdown = drawdown.cummin()
        rolling_vol = port_return.rolling(21).std() * np.sqrt(252.0)

        port_df = pd.DataFrame({
            "date":            position_values.index,
            "portfolio_name":  portfolio.name,
            "total_value":     total_value.values,
            "daily_return":    port_return.reindex(position_values.index).values,
            "cum_return":      cum_return.reindex(position_values.index).values,
            "rolling_vol_21d": rolling_vol.reindex(position_values.index).values,
            "drawdown":        drawdown.reindex(position_values.index).values,
            "max_drawdown":    max_drawdown.reindex(position_values.index).values,
        }).dropna(subset=["total_value"]).reset_index(drop=True)
        port_df["date"] = pd.to_datetime(port_df["date"])

        # Long-format attribution: one row per (date, ticker)
        attr_frames = []
        for t in position_values.columns:
            asset = pos_by_t[t].asset
            df = pd.DataFrame({
                "date":   position_values.index,
                "portfolio_name": portfolio.name,
                "ticker": t,
                "weight":          weights[t].values,
                "position_return": rets[t].values,
                "contribution_to_return": contributions[t].values,
                "asset_type": asset.asset_type.value,
                "sector":     asset.sector or "Unknown",
            })
            # Keep rows where we at least had a weight OR a contribution to record.
            df = df.dropna(subset=["weight"], how="all").reset_index(drop=True)
            attr_frames.append(df)
        attr_df = pd.concat(attr_frames, ignore_index=True) if attr_frames else empty_attr
        attr_df["date"] = pd.to_datetime(attr_df["date"])

        return port_df, attr_df

    # ── v2: trade-replay reconstruction ──────────────────────────────────────

    def compute_portfolio_history_from_trades(
        self,
        portfolio_name: str,
        start_date: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """v2: reconstruct historical positions by cumulative-summing the trade
        ledger, then compute the same daily portfolio + attribution metrics
        against those actual historical holdings.

        Returns empty DataFrames if no trades are recorded for the portfolio
        (so the caller can fall back to v1).
        """
        empty_port = pd.DataFrame(columns=[
            "date", "portfolio_name", "total_value", "daily_return",
            "cum_return", "rolling_vol_21d", "drawdown", "max_drawdown",
        ])
        empty_attr = pd.DataFrame(columns=[
            "date", "portfolio_name", "ticker", "weight",
            "position_return", "contribution_to_return", "asset_type", "sector",
        ])

        trades = self.db.list_trades(portfolio_name=portfolio_name)
        if trades.empty:
            return empty_port, empty_attr

        # Build per-trade signed quantity delta (BUY +, SELL −).
        trades = trades.copy()
        trades["trade_date"] = pd.to_datetime(trades["trade_date"])
        trades["delta_qty"] = np.where(
            trades["side"].str.upper() == "BUY",
            trades["quantity"], -trades["quantity"],
        )

        # Pivot to (date × ticker) deltas, summing multiple same-day trades.
        qty_changes = (
            trades.pivot_table(
                index="trade_date", columns="ticker",
                values="delta_qty", aggfunc="sum", fill_value=0.0,
            ).sort_index()
        )
        tickers = qty_changes.columns.tolist()

        prices = self.db.get_historical_prices(tickers, start_date=start_date)
        if prices.empty:
            return empty_port, empty_attr
        prices = prices.sort_index()

        # Reindex deltas onto the price calendar so cumulative position state
        # is defined on every trading day (0 before first trade for a ticker).
        # Reindexing with method='ffill' would carry deltas forward — we don't
        # want that — so fill missing dates with 0 and then cumsum.
        first_trade_date = qty_changes.index.min()
        # Limit price index to dates >= first trade (positions are 0 before that).
        eligible_dates = prices.index[prices.index >= first_trade_date]
        if len(eligible_dates) == 0:
            return empty_port, empty_attr

        # Build a daily delta matrix on the price calendar.
        deltas_on_calendar = qty_changes.reindex(eligible_dates, fill_value=0.0)
        # For trades that landed on a non-trading day, snap to the next trading
        # day so we don't lose any qty changes.
        off_calendar = qty_changes.index.difference(eligible_dates)
        if len(off_calendar) > 0:
            snap_to = pd.Series(eligible_dates).searchsorted(off_calendar)
            for src_d, idx in zip(off_calendar, snap_to):
                if 0 <= idx < len(eligible_dates):
                    deltas_on_calendar.loc[eligible_dates[idx]] += qty_changes.loc[src_d]

        positions_qty = deltas_on_calendar.cumsum()
        # Floor at 0 — guards against shorting (we don't model it) and tiny
        # negative residuals from SELLs that exceed the recorded BUYs.
        positions_qty = positions_qty.clip(lower=0.0)

        # Position $ values per date, using whatever prices exist that day.
        priced_tickers = [t for t in tickers if t in prices.columns]
        if not priced_tickers:
            return empty_port, empty_attr
        position_values = positions_qty[priced_tickers] * prices[priced_tickers].reindex(positions_qty.index)
        # Drop the rare row where every position is zero AND every price is NaN.
        position_values = position_values.dropna(how="all")
        if position_values.empty:
            return empty_port, empty_attr

        total_value = position_values.sum(axis=1, min_count=1)
        weights = position_values.div(total_value, axis=0)
        prev_weights = weights.shift(1)
        rets = prices[priced_tickers].reindex(position_values.index).pct_change()
        contributions = prev_weights * rets
        port_return = contributions.sum(axis=1, min_count=1)

        cumulative = (1.0 + port_return.fillna(0.0)).cumprod()
        # Anchor cum_return to the first date with non-zero portfolio value.
        first_funded = total_value[total_value > 0].first_valid_index()
        if first_funded is not None:
            cumulative.loc[cumulative.index < first_funded] = np.nan
        cum_return = cumulative - 1.0
        cummax = cumulative.cummax()
        drawdown = (cumulative - cummax) / cummax
        max_drawdown = drawdown.cummin()
        rolling_vol = port_return.rolling(21).std() * np.sqrt(252.0)

        port_df = pd.DataFrame({
            "date":            position_values.index,
            "portfolio_name":  portfolio_name,
            "total_value":     total_value.values,
            "daily_return":    port_return.reindex(position_values.index).values,
            "cum_return":      cum_return.reindex(position_values.index).values,
            "rolling_vol_21d": rolling_vol.reindex(position_values.index).values,
            "drawdown":        drawdown.reindex(position_values.index).values,
            "max_drawdown":    max_drawdown.reindex(position_values.index).values,
        }).dropna(subset=["total_value"]).reset_index(drop=True)
        port_df["date"] = pd.to_datetime(port_df["date"])

        # Asset metadata lookup (single read).
        assets_df = self.db.get_all_assets().set_index("ticker")
        def _meta(t):
            if t in assets_df.index:
                row = assets_df.loc[t]
                return str(row.get("asset_type") or "Unknown"), str(row.get("sector") or "Unknown")
            return "Unknown", "Unknown"

        attr_frames = []
        for t in priced_tickers:
            at, sector = _meta(t)
            df = pd.DataFrame({
                "date":   position_values.index,
                "portfolio_name": portfolio_name,
                "ticker": t,
                "weight":                 weights[t].values,
                "position_return":        rets[t].values,
                "contribution_to_return": contributions[t].values,
                "asset_type":             at,
                "sector":                 sector or "Unknown",
            })
            # Drop dates where this position had no weight AND no return —
            # i.e. wasn't held that day. Keeps the table much smaller.
            df = df[(df["weight"].fillna(0) > 0) | (df["position_return"].notna() & df["contribution_to_return"].notna())]
            attr_frames.append(df.reset_index(drop=True))
        attr_df = pd.concat(attr_frames, ignore_index=True) if attr_frames else empty_attr
        attr_df["date"] = pd.to_datetime(attr_df["date"])

        return port_df, attr_df

    # ── Orchestration ─────────────────────────────────────────────────────────

    def refresh_all(
        self,
        start_date: Optional[str] = None,
        portfolio_name: Optional[str] = None,
        full: bool = False,
    ) -> dict:
        """Compute and persist daily metrics for all (or one) portfolio.

        If `full` is False (default), only recomputes dates after the latest
        already-stored date — strict incremental. `full=True` recomputes the
        whole history (useful after schema changes or trade backfills).
        """
        # Decide start_date for security metrics
        sec_start = start_date
        if not full and sec_start is None:
            last = self.db.latest_security_metric_date()
            if last is not None:
                sec_start = (last - pd.Timedelta(days=30)).strftime("%Y-%m-%d")

        sec_df = self.compute_security_metrics(start_date=sec_start)
        self.db.save_daily_security_metrics(sec_df)

        port_total = 0
        attr_total = 0
        modes: dict[str, str] = {}
        names = [portfolio_name] if portfolio_name else self.db.list_portfolios()
        for name in names:
            try:
                p = self.db.get_portfolio(name)
            except Exception:
                continue

            port_start = start_date
            if not full and port_start is None:
                last = self.db.latest_portfolio_metric_date(name)
                if last is not None:
                    port_start = (last - pd.Timedelta(days=30)).strftime("%Y-%m-%d")

            # Prefer trade-replay (v2) when trades exist; else fall back to v1.
            has_trades = not self.db.list_trades(portfolio_name=name).empty
            if has_trades:
                port_df, attr_df = self.compute_portfolio_history_from_trades(
                    name, start_date=port_start,
                )
                modes[name] = "trade_replay" if not port_df.empty else "static_current"
                if port_df.empty:
                    # v2 produced nothing (e.g. trades exist but no prices yet);
                    # fall back to v1 so the user still gets something.
                    port_df, attr_df = self.compute_portfolio_history(p, start_date=port_start)
            else:
                port_df, attr_df = self.compute_portfolio_history(p, start_date=port_start)
                modes[name] = "static_current"

            self.db.save_daily_portfolio_metrics(port_df)
            self.db.save_daily_attribution(attr_df)
            port_total += len(port_df)
            attr_total += len(attr_df)

        return {
            "security_rows":    len(sec_df),
            "portfolio_rows":   port_total,
            "attribution_rows": attr_total,
            "portfolios":       names,
            "modes":            modes,
        }

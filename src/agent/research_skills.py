"""Research skills for the investment research agent.

Provides tools to look up candidate assets, fetch their price history, get
a portfolio baseline, and simulate how a proposed allocation would affect
existing portfolio metrics (VaR, drawdown, sector exposure, correlation).
"""

import json
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf
from anthropic import beta_tool

from src.collector import Collector
from src.database import Database
from src.models import Asset, AssetType, Position, Portfolio
from src.reporting import ReportingEngine

# Map yfinance quoteType → our AssetType enum
_YF_TYPE_MAP = {
    "EQUITY": AssetType.STOCK,
    "ETF": AssetType.ETF,
    "MUTUALFUND": AssetType.FUND,
    "BOND": AssetType.BOND,
    "CURRENCY": AssetType.CASH,
    "CRYPTOCURRENCY": AssetType.CRYPTO,
}


def create_research_skills(db: Database, engine: ReportingEngine) -> List:
    """Return beta_tool-decorated research skills bound to db/engine."""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _latest_price(ticker: str) -> float:
        prices = db.get_historical_prices([ticker])
        if prices.empty or ticker not in prices.columns:
            return 1.0
        series = prices[ticker].dropna()
        return float(series.iloc[-1]) if not series.empty else 1.0

    def _portfolio_metrics(tickers: list, weights: np.ndarray, prices: pd.DataFrame) -> dict:
        """Compute VaR, volatility, max drawdown for a weighted portfolio."""
        available = [t for t in tickers if t in prices.columns]
        if not available:
            return {}
        aligned_w = np.array([weights[tickers.index(t)] for t in available])
        aligned_w /= aligned_w.sum()

        returns = prices[available].pct_change().dropna()
        if returns.empty:
            return {}

        port_ret = returns.values @ aligned_w
        vol = float(port_ret.std() * np.sqrt(252))
        hist_var = float(np.percentile(port_ret, 5))

        cumulative = (1 + port_ret).cumprod()
        peak = np.maximum.accumulate(cumulative)
        max_dd = float(((cumulative - peak) / peak).min())

        return {
            "annualised_volatility_pct": round(vol * 100, 2),
            "historical_var_95_pct": round(hist_var * 100, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
        }

    def _sector_exposure(portfolio: Portfolio, extra_positions: list = None) -> dict:
        """Return {sector: pct_of_total} for positions in portfolio + any extras."""
        all_positions = list(portfolio.positions) + (extra_positions or [])
        sector_totals: dict = {}
        grand_total = 0.0
        for pos in all_positions:
            val = pos.quantity * pos.cost_basis
            sector = pos.asset.sector or "Unknown"
            sector_totals[sector] = sector_totals.get(sector, 0) + val
            grand_total += val
        if grand_total == 0:
            return {}
        return {s: round(v / grand_total * 100, 2) for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])}

    # ── Skills ────────────────────────────────────────────────────────────────

    @beta_tool
    def list_portfolios() -> str:
        """List all portfolios available in the database."""
        names = db.list_portfolios()
        if not names:
            return "No portfolios found in the database."
        return "Available portfolios:\n" + "\n".join(f"  - {n}" for n in names)

    @beta_tool
    def get_portfolio_baseline(portfolio_name: str) -> str:
        """Get the current risk and exposure baseline for a portfolio.

        Returns total value, sector breakdown, annualised volatility,
        historical VaR (95%), and max drawdown. Use this before simulating
        a new allocation so you have a before/after comparison.

        Args:
            portfolio_name: Name of the portfolio.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        prices = db.get_historical_prices(tickers)

        total_value = 0.0
        weights_list = []
        for pos in portfolio.positions:
            price = _latest_price(pos.asset.ticker)
            val = pos.quantity * price
            total_value += val
            weights_list.append(val)

        w = np.array(weights_list)
        if w.sum() > 0:
            w /= w.sum()

        metrics = _portfolio_metrics(tickers, w, prices)
        sector_exp = _sector_exposure(portfolio)

        return json.dumps({
            "portfolio": portfolio_name,
            "total_value": round(total_value, 2),
            "position_count": len(portfolio.positions),
            "sector_exposure_pct": sector_exp,
            **metrics,
        }, indent=2)

    @beta_tool
    def lookup_asset_info(tickers_csv: str) -> str:
        """Look up key information for one or more ticker symbols using live market data.

        Returns name, sector, industry, asset type, current price, 52-week range,
        and beta for each ticker. Useful for vetting candidate investments before
        simulating their impact on a portfolio.

        Args:
            tickers_csv: Comma-separated ticker symbols, e.g. "BND,VTI,GLD".
        """
        tickers = [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]
        results = {}
        for ticker in tickers:
            try:
                yf_ticker = yf.Ticker(ticker)
                info = yf_ticker.info or {}
                fast = yf_ticker.fast_info

                quote_type = info.get("quoteType", "EQUITY")
                asset_type = _YF_TYPE_MAP.get(quote_type, AssetType.STOCK).value

                results[ticker] = {
                    "name": info.get("longName") or info.get("shortName", ticker),
                    "asset_type": asset_type,
                    "sector": info.get("sector") or info.get("category", "Unknown"),
                    "industry": info.get("industry", "Unknown"),
                    "current_price": round(float(getattr(fast, "last_price", 0) or 0), 4),
                    "52w_high": round(float(getattr(fast, "year_high", 0) or 0), 4),
                    "52w_low": round(float(getattr(fast, "year_low", 0) or 0), 4),
                    "beta": round(float(info.get("beta") or 1.0), 3),
                    "market_cap": info.get("marketCap"),
                    "currency": info.get("currency", "USD"),
                    "description": (info.get("longBusinessSummary") or "")[:300] or None,
                }
            except Exception as e:
                results[ticker] = {"error": str(e)}

        return json.dumps(results, indent=2)

    @beta_tool
    def fetch_asset_prices(tickers_csv: str, period: str = "1y") -> str:
        """Download historical price data for one or more tickers from Yahoo Finance
        and store it in the local database. Also saves asset metadata (name, sector,
        type) so the tickers can be used in simulations.

        Call this before simulate_allocation for any tickers not yet in the database.

        Args:
            tickers_csv: Comma-separated ticker symbols, e.g. "BND,VTI,GLD".
            period: yfinance period string — e.g. "1y", "2y", "6mo" (default "1y").
        """
        tickers = [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]
        results = {}
        collector = Collector(db)

        for ticker in tickers:
            try:
                # Fetch and store prices
                data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
                if data.empty:
                    results[ticker] = {"status": "error", "message": "No price data returned"}
                    continue
                db.save_prices(ticker, data)

                # Fetch and store asset metadata
                info = yf.Ticker(ticker).info or {}
                quote_type = info.get("quoteType", "EQUITY")
                asset_type = _YF_TYPE_MAP.get(quote_type, AssetType.STOCK)
                asset = Asset(
                    ticker=ticker,
                    name=info.get("longName") or info.get("shortName", ticker),
                    asset_type=asset_type,
                    currency=info.get("currency", "USD"),
                    sector=info.get("sector") or info.get("category"),
                )
                db.add_asset(asset)

                results[ticker] = {
                    "status": "ok",
                    "rows_stored": len(data),
                    "name": asset.name,
                    "sector": asset.sector,
                    "asset_type": asset.asset_type.value,
                }
            except Exception as e:
                results[ticker] = {"status": "error", "message": str(e)}

        return json.dumps(results, indent=2)

    @beta_tool
    def simulate_allocation(
        portfolio_name: str,
        allocation_json: str,
        total_amount: float,
    ) -> str:
        """Simulate adding a new allocation to an existing portfolio and measure the
        impact on key risk and exposure metrics.

        Compares the combined portfolio (existing + proposed) against the current
        baseline and reports deltas for: annualised volatility, historical VaR (95%),
        max drawdown, sector exposure, and pairwise correlations.

        allocation_json is a JSON object mapping ticker symbols to portfolio
        weight fractions that must sum to 1.0, e.g.:
            {"BND": 0.5, "VTI": 0.3, "GLD": 0.2}

        Run fetch_asset_prices first for any tickers not already in the database.

        Args:
            portfolio_name: Name of the existing portfolio to extend.
            allocation_json: JSON object of {ticker: fraction} summing to 1.0.
            total_amount: Total dollars to deploy across the allocation.
        """
        try:
            allocation: dict = json.loads(allocation_json)
        except json.JSONDecodeError as e:
            return f"Invalid allocation_json: {e}"

        total_frac = sum(allocation.values())
        if abs(total_frac - 1.0) > 0.01:
            return f"allocation_json fractions must sum to 1.0 (got {total_frac:.3f})."

        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        # ── Baseline metrics ──────────────────────────────────────────────────
        existing_tickers = [pos.asset.ticker for pos in portfolio.positions]
        all_prices = db.get_historical_prices(existing_tickers)

        existing_values = {}
        for pos in portfolio.positions:
            price = float(all_prices[pos.asset.ticker].dropna().iloc[-1]) if pos.asset.ticker in all_prices.columns and not all_prices[pos.asset.ticker].dropna().empty else pos.cost_basis
            existing_values[pos.asset.ticker] = pos.quantity * price

        total_existing = sum(existing_values.values())
        existing_weights = np.array([existing_values[t] / total_existing for t in existing_tickers]) if total_existing > 0 else np.ones(len(existing_tickers)) / len(existing_tickers)

        baseline_metrics = _portfolio_metrics(existing_tickers, existing_weights, all_prices)
        baseline_sectors = _sector_exposure(portfolio)

        # ── Build proposed positions ──────────────────────────────────────────
        new_positions = []
        new_tickers = []
        missing_prices = []

        for ticker, frac in allocation.items():
            ticker = ticker.upper()
            amount = total_amount * frac
            prices_for_ticker = db.get_historical_prices([ticker])

            if ticker in prices_for_ticker.columns and not prices_for_ticker[ticker].dropna().empty:
                price = float(prices_for_ticker[ticker].dropna().iloc[-1])
            else:
                missing_prices.append(ticker)
                price = 1.0  # fallback

            quantity = amount / price if price > 0 else amount

            # Look up asset metadata from DB, else use placeholder
            all_assets_df = pd.read_parquet(db._assets_path())
            asset_row = all_assets_df[all_assets_df["ticker"] == ticker]
            if not asset_row.empty:
                row = asset_row.iloc[0]
                asset = Asset(
                    ticker=ticker,
                    name=row["name"],
                    asset_type=AssetType(row["asset_type"]),
                    currency=row.get("currency", "USD"),
                    sector=row.get("sector"),
                )
            else:
                asset = Asset(ticker=ticker, name=ticker, asset_type=AssetType.STOCK)

            new_positions.append(Position(asset=asset, quantity=quantity, cost_basis=price))
            new_tickers.append(ticker)

        # ── Combined portfolio metrics ─────────────────────────────────────────
        combined_tickers = existing_tickers + new_tickers
        combined_prices = db.get_historical_prices(combined_tickers)

        combined_values = {**existing_values}
        for pos in new_positions:
            combined_values[pos.asset.ticker] = combined_values.get(pos.asset.ticker, 0) + pos.quantity * pos.cost_basis

        total_combined = sum(combined_values.values())
        combined_weights = np.array([combined_values.get(t, 0) / total_combined for t in combined_tickers])

        combined_metrics = _portfolio_metrics(combined_tickers, combined_weights, combined_prices)

        # Sector exposure delta
        combined_sectors = _sector_exposure(portfolio, extra_positions=new_positions)
        sector_delta = {
            s: round(combined_sectors.get(s, 0) - baseline_sectors.get(s, 0), 2)
            for s in set(list(baseline_sectors.keys()) + list(combined_sectors.keys()))
        }

        # Correlation of each new asset with the existing portfolio
        rets = combined_prices.pct_change().dropna()
        existing_ret = None
        if existing_tickers and all(t in rets.columns for t in existing_tickers):
            ew = np.array([existing_values.get(t, 0) for t in existing_tickers])
            if ew.sum() > 0:
                ew /= ew.sum()
                existing_ret = rets[existing_tickers].values @ ew

        new_asset_correlations = {}
        if existing_ret is not None:
            for ticker in new_tickers:
                if ticker in rets.columns:
                    new_ret = rets[ticker].values
                    min_len = min(len(existing_ret), len(new_ret))
                    if min_len > 5:
                        corr = float(np.corrcoef(existing_ret[-min_len:], new_ret[-min_len:])[0, 1])
                        new_asset_correlations[ticker] = round(corr, 4)

        # ── Compose result ────────────────────────────────────────────────────
        def _delta(key):
            b = baseline_metrics.get(key)
            c = combined_metrics.get(key)
            if b is None or c is None:
                return None
            return round(c - b, 4)

        result = {
            "portfolio": portfolio_name,
            "total_amount_deployed": total_amount,
            "allocation": {t.upper(): frac for t, frac in allocation.items()},
            "baseline": baseline_metrics,
            "combined": combined_metrics,
            "deltas": {
                "annualised_volatility_pct": _delta("annualised_volatility_pct"),
                "historical_var_95_pct": _delta("historical_var_95_pct"),
                "max_drawdown_pct": _delta("max_drawdown_pct"),
            },
            "sector_exposure": {
                "before": baseline_sectors,
                "after": combined_sectors,
                "delta": {k: v for k, v in sector_delta.items() if abs(v) > 0.1},
            },
            "new_asset_correlation_with_existing_portfolio": new_asset_correlations,
        }

        if missing_prices:
            result["warning"] = (
                f"No stored prices for {missing_prices}. "
                "Run fetch_asset_prices first for accurate simulation. "
                "Falling back to price=1 for these tickers."
            )

        return json.dumps(result, indent=2)

    return [
        list_portfolios,
        get_portfolio_baseline,
        lookup_asset_info,
        fetch_asset_prices,
        simulate_allocation,
    ]

"""Risk management skills for the investment monitoring agent.

Each skill is a @beta_tool decorated function that provides a specific risk
analysis capability. Skills are created via a factory so they can close over
the shared Database and ReportingEngine instances.
"""

import json
from datetime import timedelta
from typing import List

import numpy as np
from anthropic import beta_tool

from src.database import Database
from src.reporting import ReportingEngine


def create_risk_skills(db: Database, engine: ReportingEngine) -> List:
    """Return a list of beta_tool-decorated risk skills bound to the given db/engine."""

    @beta_tool
    def list_portfolios() -> str:
        """List all portfolios available in the database."""
        names = db.list_portfolios()
        if not names:
            return "No portfolios found in the database."
        return "Available portfolios:\n" + "\n".join(f"  - {n}" for n in names)

    @beta_tool
    def get_portfolio_summary(portfolio_name: str) -> str:
        """Get a breakdown of all positions in a portfolio: ticker, asset type, sector,
        quantity, cost basis, market value, and percentage weight.

        Args:
            portfolio_name: Name of the portfolio to summarize.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        total_cost = portfolio.total_cost()
        positions = []
        for pos in portfolio.positions:
            value = pos.quantity * pos.cost_basis
            positions.append({
                "ticker": pos.asset.ticker,
                "name": pos.asset.name,
                "type": pos.asset.asset_type.value,
                "sector": pos.asset.sector or "Unknown",
                "quantity": pos.quantity,
                "cost_basis_per_unit": pos.cost_basis,
                "market_value": round(value, 2),
                "weight_pct": round(value / total_cost * 100, 2) if total_cost else 0,
            })

        positions.sort(key=lambda x: x["market_value"], reverse=True)
        return json.dumps({
            "portfolio": portfolio_name,
            "total_value": round(total_cost, 2),
            "position_count": len(positions),
            "positions": positions,
        }, indent=2)

    @beta_tool
    def get_risk_metrics(portfolio_name: str) -> str:
        """Calculate key risk metrics for a portfolio: annualized volatility,
        historical VaR (95%), and Monte Carlo VaR (95%). Requires price data
        — run 'collect' first if metrics are unavailable.

        Args:
            portfolio_name: Name of the portfolio to analyze.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        try:
            metrics = engine.get_portfolio_risk_metrics(portfolio)
        except Exception as e:
            return f"Could not compute risk metrics: {e}. Ensure price data has been collected (run: invest-monitor collect)."

        cov_matrix = metrics.pop("Covariance Matrix")
        result = {k: round(float(v), 6) for k, v in metrics.items()}
        result["covariance_matrix"] = {
            col: {idx: round(float(val), 6) for idx, val in row.items()}
            for col, row in cov_matrix.to_dict().items()
        }
        return json.dumps(result, indent=2)

    @beta_tool
    def get_exposure_breakdown(portfolio_name: str) -> str:
        """Get portfolio exposure grouped by asset type and sector, showing
        the dollar value and percentage weight for each group.

        Args:
            portfolio_name: Name of the portfolio to analyze.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        df = engine.get_portfolio_exposure(portfolio)
        total = df["Weight"].sum()
        df = df.copy()
        df["weight_pct"] = (df["Weight"] / total * 100).round(2)
        df["Weight"] = df["Weight"].round(2)
        return df.reset_index().rename(columns={"Weight": "value"}).to_json(orient="records", indent=2)

    @beta_tool
    def check_concentration_risk(portfolio_name: str, threshold_pct: float = 20.0) -> str:
        """Identify positions whose weight in the portfolio exceeds a given threshold,
        signaling potential concentration risk.

        Args:
            portfolio_name: Name of the portfolio to check.
            threshold_pct: Concentration threshold as a percentage of portfolio value (default: 20.0).
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        total_cost = portfolio.total_cost()
        if total_cost == 0:
            return "Portfolio has zero value."

        alerts = []
        for pos in portfolio.positions:
            value = pos.quantity * pos.cost_basis
            weight = value / total_cost * 100
            if weight >= threshold_pct:
                alerts.append({
                    "ticker": pos.asset.ticker,
                    "name": pos.asset.name,
                    "type": pos.asset.asset_type.value,
                    "sector": pos.asset.sector or "Unknown",
                    "weight_pct": round(weight, 2),
                    "market_value": round(value, 2),
                    "excess_over_threshold_pct": round(weight - threshold_pct, 2),
                })

        alerts.sort(key=lambda x: x["weight_pct"], reverse=True)
        if not alerts:
            return f"No positions exceed the {threshold_pct}% concentration threshold."

        return json.dumps({
            "threshold_pct": threshold_pct,
            "total_portfolio_value": round(total_cost, 2),
            "concentration_alerts": alerts,
        }, indent=2)

    @beta_tool
    def get_correlation_matrix(portfolio_name: str) -> str:
        """Compute pairwise return correlations between all assets in a portfolio.
        High correlations (>0.7) indicate diversification is limited between those assets.
        Requires price history.

        Args:
            portfolio_name: Name of the portfolio to analyze.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        try:
            returns = engine.calculate_returns(tickers)
        except Exception as e:
            return f"Could not compute correlations: {e}."

        if returns.empty:
            return "No price data available. Run 'invest-monitor collect' first."

        corr = returns.corr().round(4)

        # Flag high-correlation pairs
        high_corr_pairs = []
        cols = corr.columns.tolist()
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                val = float(corr.iloc[i, j])
                if abs(val) >= 0.7:
                    high_corr_pairs.append({
                        "asset_a": cols[i],
                        "asset_b": cols[j],
                        "correlation": round(val, 4),
                        "risk_note": "high positive correlation — limited diversification benefit" if val > 0 else "high negative correlation — natural hedge",
                    })

        return json.dumps({
            "correlation_matrix": corr.to_dict(),
            "high_correlation_pairs": high_corr_pairs,
        }, indent=2)

    @beta_tool
    def calculate_max_drawdown(portfolio_name: str) -> str:
        """Calculate the maximum drawdown (peak-to-trough decline) for each asset and
        the overall portfolio. A larger drawdown indicates higher historical downside risk.

        Args:
            portfolio_name: Name of the portfolio to analyze.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        prices = db.get_historical_prices(tickers)

        if prices.empty:
            return "No price data available. Run 'invest-monitor collect' first."

        results = {}
        for ticker in prices.columns:
            series = prices[ticker].dropna()
            if len(series) < 2:
                continue
            cummax = series.cummax()
            dd = (series - cummax) / cummax
            results[ticker] = {
                "max_drawdown_pct": round(float(dd.min()) * 100, 2),
                "current_drawdown_pct": round(float(dd.iloc[-1]) * 100, 2),
                "peak_price": round(float(cummax.max()), 4),
                "current_price": round(float(series.iloc[-1]), 4),
            }

        # Portfolio-level weighted drawdown
        weights_map = {pos.asset.ticker: pos.quantity * pos.cost_basis for pos in portfolio.positions}
        total_w = sum(weights_map.values())
        available = [t for t in prices.columns if t in weights_map]
        if available and total_w > 0:
            w_arr = [weights_map.get(t, 0) / total_w for t in available]
            port_prices = prices[available].dot(w_arr)
            cummax = port_prices.cummax()
            dd = (port_prices - cummax) / cummax
            results["PORTFOLIO (weighted)"] = {
                "max_drawdown_pct": round(float(dd.min()) * 100, 2),
                "current_drawdown_pct": round(float(dd.iloc[-1]) * 100, 2),
            }

        return json.dumps(results, indent=2)

    @beta_tool
    def get_price_performance(portfolio_name: str) -> str:
        """Get price return performance for each asset over multiple look-back periods:
        1 month, 3 months, 6 months, and 1 year.

        Args:
            portfolio_name: Name of the portfolio to analyze.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        prices = db.get_historical_prices(tickers)

        if prices.empty:
            return "No price data available. Run 'invest-monitor collect' first."

        latest_date = prices.index.max()
        periods = {
            "1M": latest_date - timedelta(days=30),
            "3M": latest_date - timedelta(days=90),
            "6M": latest_date - timedelta(days=180),
            "1Y": latest_date - timedelta(days=365),
        }

        results = {}
        for ticker in prices.columns:
            series = prices[ticker].dropna()
            if series.empty:
                continue
            current = float(series.iloc[-1])
            entry: dict = {"current_price": round(current, 4)}
            for label, cutoff in periods.items():
                past = series[series.index <= cutoff]
                if not past.empty:
                    past_price = float(past.iloc[-1])
                    entry[f"return_{label}_pct"] = round((current - past_price) / past_price * 100, 2)
                else:
                    entry[f"return_{label}_pct"] = None
            results[ticker] = entry

        return json.dumps(results, indent=2)

    # ── Scenario analysis skills ───────────────────────────────────────────────

    # Named historical / macro scenarios: maps asset type and sector to a
    # representative % shock derived from actual peak-to-trough figures.
    _SCENARIOS: dict = {
        "2008_financial_crisis": {
            "description": (
                "Global financial crisis (Oct 2007 – Mar 2009). "
                "S&P 500 -56 %, investment-grade bonds +8 %."
            ),
            "asset_type_shocks": {
                "Stock": -56, "ETF": -50, "Fund": -45,
                "Bond": 8, "Cash": 0, "Crypto": -30,
            },
            "sector_shocks": {
                "Financials": -75, "Real Estate": -40,
                "Technology": -52, "Energy": -60,
                "Consumer Discretionary": -55,
            },
        },
        "covid_crash_2020": {
            "description": (
                "COVID-19 crash (Feb–Mar 2020). "
                "S&P 500 -34 % in five weeks."
            ),
            "asset_type_shocks": {
                "Stock": -34, "ETF": -30, "Fund": -28,
                "Bond": 5, "Cash": 0, "Crypto": -50,
            },
            "sector_shocks": {
                "Consumer Discretionary": -45, "Energy": -55,
                "Technology": -20, "Healthcare": -10,
                "Utilities": -15,
            },
        },
        "dot_com_bust": {
            "description": (
                "Dot-com bust (Mar 2000 – Oct 2002). "
                "Nasdaq -78 %, S&P 500 -49 %."
            ),
            "asset_type_shocks": {
                "Stock": -49, "ETF": -45, "Fund": -40,
                "Bond": 12, "Cash": 0, "Crypto": 0,
            },
            "sector_shocks": {
                "Technology": -78, "Telecommunications": -70,
                "Media": -50, "Financials": -20,
                "Consumer Staples": -10,
            },
        },
        "rate_hike_shock": {
            "description": (
                "Rapid rate hikes (2022-style). "
                "Bonds -20 %, growth stocks -30 %, energy +50 %."
            ),
            "asset_type_shocks": {
                "Stock": -20, "ETF": -18, "Bond": -20,
                "Fund": -15, "Cash": 0, "Crypto": -60,
            },
            "sector_shocks": {
                "Technology": -35, "Real Estate": -25,
                "Utilities": -15, "Financials": 5, "Energy": 50,
            },
        },
        "inflation_spike": {
            "description": (
                "High-inflation environment. "
                "Commodities +25 %, long bonds -25 %, growth equities -20 %."
            ),
            "asset_type_shocks": {
                "Stock": -15, "Bond": -25, "ETF": -12,
                "Fund": -10, "Cash": -5, "Crypto": -20,
            },
            "sector_shocks": {
                "Energy": 30, "Materials": 25, "Technology": -22,
                "Consumer Discretionary": -18, "Utilities": -12,
            },
        },
    }

    @beta_tool
    def list_stress_scenarios() -> str:
        """List all available named stress scenarios that can be applied to a portfolio."""
        rows = []
        for key, info in _SCENARIOS.items():
            rows.append({"scenario_id": key, "description": info["description"]})
        return json.dumps(rows, indent=2)

    @beta_tool
    def run_stress_test(portfolio_name: str, scenario_name: str) -> str:
        """Apply a named historical or macro stress scenario to a portfolio and show
        the estimated P&L impact per position and for the overall portfolio.

        Sector shocks override asset-type shocks when a position's sector matches.
        Use list_stress_scenarios to see available scenario IDs.

        Args:
            portfolio_name: Name of the portfolio to stress-test.
            scenario_name: Scenario ID (e.g. '2008_financial_crisis', 'rate_hike_shock').
        """
        scenario = _SCENARIOS.get(scenario_name)
        if scenario is None:
            available = ", ".join(_SCENARIOS.keys())
            return f"Unknown scenario '{scenario_name}'. Available: {available}"

        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        type_shocks = scenario["asset_type_shocks"]
        sector_shocks = scenario["sector_shocks"]

        total_value = portfolio.total_cost()
        position_results = []
        total_pnl = 0.0

        for pos in portfolio.positions:
            value = pos.quantity * pos.cost_basis
            asset_type = pos.asset.asset_type.value
            sector = pos.asset.sector or ""

            # Sector shock takes priority if it matches, else fall back to asset type
            if sector and sector in sector_shocks:
                shock_pct = sector_shocks[sector]
                shock_source = f"sector ({sector})"
            elif asset_type in type_shocks:
                shock_pct = type_shocks[asset_type]
                shock_source = f"asset type ({asset_type})"
            else:
                shock_pct = 0.0
                shock_source = "no matching shock (0%)"

            pnl = value * shock_pct / 100
            total_pnl += pnl
            position_results.append({
                "ticker": pos.asset.ticker,
                "name": pos.asset.name,
                "current_value": round(value, 2),
                "shock_pct": shock_pct,
                "shock_source": shock_source,
                "estimated_pnl": round(pnl, 2),
                "stressed_value": round(value + pnl, 2),
            })

        position_results.sort(key=lambda x: x["estimated_pnl"])

        return json.dumps({
            "scenario": scenario_name,
            "description": scenario["description"],
            "portfolio": portfolio_name,
            "current_total_value": round(total_value, 2),
            "estimated_total_pnl": round(total_pnl, 2),
            "stressed_total_value": round(total_value + total_pnl, 2),
            "portfolio_return_pct": round(total_pnl / total_value * 100, 2) if total_value else 0,
            "positions": position_results,
        }, indent=2)

    @beta_tool
    def apply_custom_shock(portfolio_name: str, shocks_json: str) -> str:
        """Apply arbitrary percentage price shocks to specific tickers, asset types,
        or sectors and show the resulting portfolio P&L impact.

        shocks_json is a JSON object where each key is a ticker symbol, asset type
        (e.g. 'Stock', 'Bond', 'ETF'), or sector name, and each value is the
        percentage change to apply (negative = loss). Ticker-level shocks take
        highest priority, then sector, then asset type.

        Example shocks_json:
            {"AAPL": -15, "Technology": -10, "Bond": 5}

        Args:
            portfolio_name: Name of the portfolio to shock.
            shocks_json: JSON string mapping ticker / asset type / sector to % shock.
        """
        try:
            shocks: dict = json.loads(shocks_json)
        except json.JSONDecodeError as e:
            return f"Invalid shocks_json — must be a JSON object: {e}"

        if not isinstance(shocks, dict):
            return "shocks_json must be a JSON object, e.g. {\"AAPL\": -15}."

        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        total_value = portfolio.total_cost()
        position_results = []
        total_pnl = 0.0

        for pos in portfolio.positions:
            value = pos.quantity * pos.cost_basis
            ticker = pos.asset.ticker
            asset_type = pos.asset.asset_type.value
            sector = pos.asset.sector or ""

            if ticker in shocks:
                shock_pct = float(shocks[ticker])
                shock_source = f"ticker ({ticker})"
            elif sector and sector in shocks:
                shock_pct = float(shocks[sector])
                shock_source = f"sector ({sector})"
            elif asset_type in shocks:
                shock_pct = float(shocks[asset_type])
                shock_source = f"asset type ({asset_type})"
            else:
                shock_pct = 0.0
                shock_source = "unaffected"

            pnl = value * shock_pct / 100
            total_pnl += pnl
            position_results.append({
                "ticker": ticker,
                "name": pos.asset.name,
                "current_value": round(value, 2),
                "shock_pct": shock_pct,
                "shock_source": shock_source,
                "estimated_pnl": round(pnl, 2),
                "stressed_value": round(value + pnl, 2),
            })

        position_results.sort(key=lambda x: x["estimated_pnl"])

        return json.dumps({
            "portfolio": portfolio_name,
            "shocks_applied": shocks,
            "current_total_value": round(total_value, 2),
            "estimated_total_pnl": round(total_pnl, 2),
            "stressed_total_value": round(total_value + total_pnl, 2),
            "portfolio_return_pct": round(total_pnl / total_value * 100, 2) if total_value else 0,
            "positions": position_results,
        }, indent=2)

    @beta_tool
    def get_cumulative_returns(portfolio_name: str, start_date: str = None) -> str:
        """Get cumulative price return for each asset in a portfolio from the start of
        available price history (or a specified date) to the most recent price.

        Returns the total percentage gain/loss per asset over the period.

        Args:
            portfolio_name: Name of the portfolio to analyze.
            start_date: Optional ISO date string (YYYY-MM-DD) to anchor the start of
                the return calculation. Defaults to the earliest available price.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        cum_returns = engine.calculate_cumulative_returns(tickers, start_date=start_date)

        if cum_returns.empty:
            return "No price data available. Run 'invest-monitor collect' first."

        results = {}
        for ticker in cum_returns.columns:
            series = cum_returns[ticker].dropna()
            if series.empty:
                continue
            results[ticker] = {
                "start_date": str(series.index[0].date()),
                "end_date": str(series.index[-1].date()),
                "cumulative_return_pct": round(float(series.iloc[-1]) * 100, 2),
            }

        return json.dumps(results, indent=2)

    @beta_tool
    def simulate_forward(
        portfolio_name: str,
        days: int = 63,
        num_simulations: int = 5000,
    ) -> str:
        """Run a Monte Carlo simulation of portfolio value over a future time horizon
        using the covariance structure of historical returns. Reports percentile outcomes
        (P5, P25, P50, P75, P95) and the probability of loss.

        Requires historical price data — run 'invest-monitor collect' first.

        Args:
            portfolio_name: Name of the portfolio to simulate.
            days: Number of trading days to simulate forward (default: 63 ≈ 1 quarter).
            num_simulations: Number of Monte Carlo paths (default: 5000).
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        try:
            returns = engine.calculate_returns(tickers)
        except Exception as e:
            return f"Could not load return data: {e}."

        if returns.empty:
            return "No price data available. Run 'invest-monitor collect' first."

        # Align tickers to columns that actually have price data
        available = [t for t in tickers if t in returns.columns]
        if not available:
            return "No price data found for any position in the portfolio."

        returns = returns[available].dropna()

        weights_map = {pos.asset.ticker: pos.quantity * pos.cost_basis for pos in portfolio.positions}
        total_value = sum(weights_map.values())
        w = np.array([weights_map.get(t, 0) / total_value for t in available])

        mu = returns.mean().values          # daily mean returns per asset
        cov = returns.cov().values          # daily covariance matrix

        # Cholesky decomposition for correlated multivariate normal draws
        try:
            L = np.linalg.cholesky(cov)
        except np.linalg.LinAlgError:
            # Fall back to nearest PSD matrix if cov is ill-conditioned
            eigvals, eigvecs = np.linalg.eigh(cov)
            eigvals = np.maximum(eigvals, 0)
            cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
            L = np.linalg.cholesky(cov + np.eye(len(cov)) * 1e-8)

        rng = np.random.default_rng(seed=42)
        # Shape: (num_simulations, days, n_assets)
        z = rng.standard_normal((num_simulations, days, len(available)))
        # Apply covariance structure: correlated daily returns
        daily_returns = (z @ L.T) + mu  # broadcast mu over (sims, days)

        # Compound daily returns into cumulative portfolio return per path
        port_daily = daily_returns @ w                          # (num_simulations, days)
        cum_returns = (1 + port_daily).prod(axis=1) - 1        # (num_simulations,)
        final_values = total_value * (1 + cum_returns)

        pcts = {
            "P5":  float(np.percentile(final_values, 5)),
            "P25": float(np.percentile(final_values, 25)),
            "P50": float(np.percentile(final_values, 50)),
            "P75": float(np.percentile(final_values, 75)),
            "P95": float(np.percentile(final_values, 95)),
        }
        prob_loss = float(np.mean(cum_returns < 0))
        expected_return = float(np.mean(cum_returns))
        annualised_vol = float(np.std(port_daily) * np.sqrt(252))

        return json.dumps({
            "portfolio": portfolio_name,
            "simulation_days": days,
            "num_simulations": num_simulations,
            "current_value": round(total_value, 2),
            "expected_return_pct": round(expected_return * 100, 2),
            "annualised_volatility_pct": round(annualised_vol * 100, 2),
            "probability_of_loss_pct": round(prob_loss * 100, 2),
            "percentile_outcomes": {k: round(v, 2) for k, v in pcts.items()},
            "note": (
                f"Based on {len(returns)} days of historical returns. "
                "Assumes returns are drawn from a multivariate normal distribution."
            ),
        }, indent=2)

    return [
        list_portfolios,
        get_portfolio_summary,
        get_risk_metrics,
        get_exposure_breakdown,
        check_concentration_risk,
        get_correlation_matrix,
        calculate_max_drawdown,
        get_price_performance,
        get_cumulative_returns,
        list_stress_scenarios,
        run_stress_test,
        apply_custom_shock,
        simulate_forward,
    ]

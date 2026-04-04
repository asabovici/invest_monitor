"""Wealth management skills for the wealth agent.

Covers areas the risk agent does not: current P&L, total return, goal
projection with contributions, rebalancing, portfolio optimisation, tax-loss
harvesting, and diversification scoring.
"""

import json
from typing import List

import numpy as np
from anthropic import beta_tool
from scipy.optimize import minimize

from src.database import Database
from src.reporting import ReportingEngine


def create_wealth_skills(db: Database, engine: ReportingEngine) -> List:
    """Return beta_tool-decorated wealth skills bound to db/engine."""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _latest_prices(tickers: list) -> dict:
        """Return {ticker: latest_price} using the last row in each price series."""
        prices = db.get_historical_prices(tickers)
        if prices.empty:
            return {t: 1.0 for t in tickers}
        return {t: float(prices[t].dropna().iloc[-1]) for t in prices.columns if not prices[t].dropna().empty}

    # ── Skills ────────────────────────────────────────────────────────────────

    @beta_tool
    def list_portfolios() -> str:
        """List all portfolios available in the database."""
        names = db.list_portfolios()
        if not names:
            return "No portfolios found in the database."
        return "Available portfolios:\n" + "\n".join(f"  - {n}" for n in names)

    @beta_tool
    def get_portfolio_value(portfolio_name: str) -> str:
        """Get the current market value of each position using the latest stored
        prices, alongside the original cost basis and unrealised P&L.

        Args:
            portfolio_name: Name of the portfolio.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        latest = _latest_prices(tickers)

        rows = []
        total_cost = 0.0
        total_market = 0.0
        for pos in portfolio.positions:
            cost = pos.quantity * pos.cost_basis
            price = latest.get(pos.asset.ticker, pos.cost_basis)
            market = pos.quantity * price
            pnl = market - cost
            total_cost += cost
            total_market += market
            rows.append({
                "ticker": pos.asset.ticker,
                "name": pos.asset.name,
                "quantity": pos.quantity,
                "cost_basis_per_share": round(pos.cost_basis, 4),
                "latest_price": round(price, 4),
                "total_cost": round(cost, 2),
                "market_value": round(market, 2),
                "unrealised_pnl": round(pnl, 2),
                "unrealised_pnl_pct": round(pnl / cost * 100, 2) if cost else 0,
            })

        rows.sort(key=lambda x: x["unrealised_pnl"], reverse=True)
        return json.dumps({
            "portfolio": portfolio_name,
            "total_cost": round(total_cost, 2),
            "total_market_value": round(total_market, 2),
            "total_unrealised_pnl": round(total_market - total_cost, 2),
            "total_unrealised_pnl_pct": round((total_market - total_cost) / total_cost * 100, 2) if total_cost else 0,
            "positions": rows,
        }, indent=2)

    @beta_tool
    def get_total_return(portfolio_name: str) -> str:
        """Calculate total return per position and for the whole portfolio based on
        historical price performance since the cost-basis date (approximated by
        comparing cost basis per share to the latest price).

        Also categorises positions into winners, losers, and flat.

        Args:
            portfolio_name: Name of the portfolio.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        latest = _latest_prices(tickers)

        winners, losers, flat = [], [], []
        total_cost = total_market = 0.0

        for pos in portfolio.positions:
            cost = pos.quantity * pos.cost_basis
            price = latest.get(pos.asset.ticker, pos.cost_basis)
            market = pos.quantity * price
            pnl = market - cost
            pnl_pct = pnl / cost * 100 if cost else 0
            total_cost += cost
            total_market += market

            entry = {
                "ticker": pos.asset.ticker,
                "name": pos.asset.name,
                "unrealised_pnl": round(pnl, 2),
                "return_pct": round(pnl_pct, 2),
                "market_value": round(market, 2),
            }
            if pnl_pct > 0.5:
                winners.append(entry)
            elif pnl_pct < -0.5:
                losers.append(entry)
            else:
                flat.append(entry)

        total_pnl = total_market - total_cost
        return json.dumps({
            "portfolio": portfolio_name,
            "total_return_pct": round(total_pnl / total_cost * 100, 2) if total_cost else 0,
            "total_unrealised_pnl": round(total_pnl, 2),
            "winners": sorted(winners, key=lambda x: x["return_pct"], reverse=True),
            "losers": sorted(losers, key=lambda x: x["return_pct"]),
            "flat": flat,
        }, indent=2)

    @beta_tool
    def calculate_sharpe_ratio(portfolio_name: str, risk_free_rate_pct: float = 4.5) -> str:
        """Calculate the annualised Sharpe ratio for a portfolio: excess return over
        the risk-free rate divided by annualised volatility.  Also returns the
        Sortino ratio (downside deviation only).

        Args:
            portfolio_name: Name of the portfolio.
            risk_free_rate_pct: Annual risk-free rate as a percentage (default 4.5).
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

        available = [t for t in tickers if t in returns.columns]
        returns = returns[available].dropna()

        weights_map = {pos.asset.ticker: pos.quantity * pos.cost_basis for pos in portfolio.positions}
        total_w = sum(weights_map.values())
        w = np.array([weights_map.get(t, 0) / total_w for t in available])

        port_returns = returns.values @ w
        ann_return = float(port_returns.mean() * 252)
        ann_vol = float(port_returns.std() * np.sqrt(252))
        rf_daily = risk_free_rate_pct / 100 / 252

        sharpe = (port_returns.mean() - rf_daily) / port_returns.std() * np.sqrt(252) if port_returns.std() > 0 else 0

        downside = port_returns[port_returns < rf_daily]
        sortino_denom = float(np.std(downside) * np.sqrt(252)) if len(downside) > 1 else 0
        sortino = (ann_return - risk_free_rate_pct / 100) / sortino_denom if sortino_denom > 0 else 0

        return json.dumps({
            "portfolio": portfolio_name,
            "risk_free_rate_pct": risk_free_rate_pct,
            "annualised_return_pct": round(ann_return * 100, 2),
            "annualised_volatility_pct": round(ann_vol * 100, 2),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "interpretation": {
                "sharpe_above_1": "Generally considered good",
                "sharpe_above_2": "Very good",
                "sharpe_below_0": "Portfolio underperforms risk-free rate on a risk-adjusted basis",
            },
            "data_days": len(port_returns),
        }, indent=2)

    @beta_tool
    def get_diversification_score(portfolio_name: str) -> str:
        """Score portfolio diversification on a 0–100 scale using three factors:
        concentration (Herfindahl index), breadth (unique sectors and asset types),
        and correlation (average pairwise correlation between holdings).

        Args:
            portfolio_name: Name of the portfolio.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        latest = _latest_prices(tickers)
        total_market = sum(
            pos.quantity * latest.get(pos.asset.ticker, pos.cost_basis)
            for pos in portfolio.positions
        )

        weights = []
        sectors = set()
        asset_types = set()
        for pos in portfolio.positions:
            price = latest.get(pos.asset.ticker, pos.cost_basis)
            w = pos.quantity * price / total_market if total_market else 0
            weights.append(w)
            if pos.asset.sector:
                sectors.add(pos.asset.sector)
            asset_types.add(pos.asset.asset_type.value)

        # Concentration score: 100 = perfectly equal weight, 0 = one position
        hhi = sum(w ** 2 for w in weights)
        n = len(weights)
        min_hhi = 1 / n if n > 0 else 1
        concentration_score = (1 - hhi) / (1 - min_hhi) * 100 if (1 - min_hhi) > 0 else 0

        # Breadth score: based on number of sectors and asset types
        sector_score = min(len(sectors) / 5 * 100, 100)
        type_score = min(len(asset_types) / 3 * 100, 100)
        breadth_score = (sector_score + type_score) / 2

        # Correlation score: low average correlation = high score
        corr_score = 50.0  # default when no price data
        avg_corr = None
        try:
            rets = engine.calculate_returns(tickers)
            if not rets.empty:
                available = [t for t in tickers if t in rets.columns]
                if len(available) > 1:
                    corr_matrix = rets[available].corr()
                    upper = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
                    avg_corr = float(np.mean(upper))
                    corr_score = max(0, (1 - avg_corr) * 100)
        except Exception:
            pass

        overall = round(concentration_score * 0.4 + breadth_score * 0.3 + corr_score * 0.3, 1)

        return json.dumps({
            "portfolio": portfolio_name,
            "diversification_score": overall,
            "score_interpretation": (
                "Excellent (>80)" if overall > 80
                else "Good (60–80)" if overall > 60
                else "Moderate (40–60)" if overall > 40
                else "Poor (<40)"
            ),
            "components": {
                "concentration_score": round(concentration_score, 1),
                "breadth_score": round(breadth_score, 1),
                "correlation_score": round(corr_score, 1),
            },
            "details": {
                "num_positions": n,
                "unique_sectors": sorted(sectors),
                "unique_asset_types": sorted(asset_types),
                "herfindahl_index": round(hhi, 4),
                "average_pairwise_correlation": round(avg_corr, 4) if avg_corr is not None else "unavailable",
            },
        }, indent=2)

    @beta_tool
    def suggest_rebalance(portfolio_name: str, target_allocation_json: str) -> str:
        """Compare the portfolio's current allocation to a target allocation and
        suggest buy / sell trades (in dollar amounts) to rebalance.

        target_allocation_json is a JSON object mapping asset type names or ticker
        symbols to target percentage weights that must sum to 100.

        Examples:
            By asset type: {"Stock": 60, "Bond": 30, "ETF": 10}
            By ticker:     {"AAPL": 40, "MSFT": 40, "BND": 20}

        Args:
            portfolio_name: Name of the portfolio to rebalance.
            target_allocation_json: JSON string with target weights summing to 100.
        """
        try:
            targets: dict = json.loads(target_allocation_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

        total_target = sum(targets.values())
        if abs(total_target - 100) > 0.5:
            return f"Target weights must sum to 100 (got {total_target:.1f})."

        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        latest = _latest_prices(tickers)

        # Build current state
        positions_map = {}
        total_market = 0.0
        for pos in portfolio.positions:
            price = latest.get(pos.asset.ticker, pos.cost_basis)
            market = pos.quantity * price
            total_market += market
            positions_map[pos.asset.ticker] = {
                "name": pos.asset.name,
                "asset_type": pos.asset.asset_type.value,
                "market_value": market,
                "latest_price": price,
            }

        # Determine whether targets are by ticker or by asset type
        ticker_set = set(positions_map.keys())
        type_set = {pos.asset.asset_type.value for pos in portfolio.positions}
        by_ticker = bool(ticker_set & set(targets.keys()))

        trades = []
        for pos in portfolio.positions:
            info = positions_map[pos.asset.ticker]
            if by_ticker:
                target_pct = targets.get(pos.asset.ticker, 0)
            else:
                target_pct = targets.get(info["asset_type"], 0)

            current_pct = info["market_value"] / total_market * 100 if total_market else 0
            target_value = total_market * target_pct / 100
            delta = target_value - info["market_value"]
            shares = delta / info["latest_price"] if info["latest_price"] else 0

            trades.append({
                "ticker": pos.asset.ticker,
                "name": info["name"],
                "asset_type": info["asset_type"],
                "current_value": round(info["market_value"], 2),
                "current_pct": round(current_pct, 2),
                "target_pct": target_pct,
                "target_value": round(target_value, 2),
                "trade_amount": round(delta, 2),
                "trade_shares": round(shares, 4),
                "action": "BUY" if delta > 1 else "SELL" if delta < -1 else "HOLD",
            })

        trades.sort(key=lambda x: x["trade_amount"])
        return json.dumps({
            "portfolio": portfolio_name,
            "total_market_value": round(total_market, 2),
            "rebalancing_trades": trades,
            "note": "Amounts are estimates based on latest stored prices.",
        }, indent=2)

    @beta_tool
    def run_goal_projection(
        portfolio_name: str,
        goal_amount: float,
        years: float,
        monthly_contribution: float = 0.0,
        num_simulations: int = 5000,
    ) -> str:
        """Project the probability of reaching a financial goal by a target date using
        Monte Carlo simulation, incorporating the portfolio's historical return and
        volatility, plus optional ongoing monthly contributions.

        Args:
            portfolio_name: Name of the portfolio to use as starting value.
            goal_amount: Target portfolio value in dollars.
            years: Time horizon in years.
            monthly_contribution: Monthly cash added to the portfolio (default 0).
            num_simulations: Number of Monte Carlo paths (default 5000).
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        latest = _latest_prices(tickers)
        current_value = sum(
            pos.quantity * latest.get(pos.asset.ticker, pos.cost_basis)
            for pos in portfolio.positions
        )

        # Get historical return stats
        try:
            rets = engine.calculate_returns(tickers)
        except Exception as e:
            return f"Could not load return data: {e}."

        if rets.empty:
            return "No price data available. Run 'invest-monitor collect' first."

        available = [t for t in tickers if t in rets.columns]
        rets = rets[available].dropna()
        weights_map = {pos.asset.ticker: pos.quantity * pos.cost_basis for pos in portfolio.positions}
        total_w = sum(weights_map.values())
        w = np.array([weights_map.get(t, 0) / total_w for t in available])
        port_daily = rets.values @ w

        daily_mu = float(port_daily.mean())
        daily_sigma = float(port_daily.std())
        trading_days = int(years * 252)
        monthly_days = 21  # approx trading days per month

        rng = np.random.default_rng(seed=42)
        paths = np.zeros((num_simulations, trading_days + 1))
        paths[:, 0] = current_value

        contribution_per_period = monthly_contribution

        for day in range(1, trading_days + 1):
            daily_ret = rng.normal(daily_mu, daily_sigma, num_simulations)
            paths[:, day] = paths[:, day - 1] * (1 + daily_ret)
            if monthly_days > 0 and day % monthly_days == 0:
                paths[:, day] += contribution_per_period

        final_values = paths[:, -1]
        prob_success = float(np.mean(final_values >= goal_amount))
        total_contributions = monthly_contribution * years * 12

        return json.dumps({
            "portfolio": portfolio_name,
            "current_value": round(current_value, 2),
            "goal_amount": round(goal_amount, 2),
            "years": years,
            "monthly_contribution": monthly_contribution,
            "total_contributions": round(total_contributions, 2),
            "probability_of_success_pct": round(prob_success * 100, 1),
            "expected_value_at_horizon": round(float(np.mean(final_values)), 2),
            "percentile_outcomes": {
                "P10": round(float(np.percentile(final_values, 10)), 2),
                "P25": round(float(np.percentile(final_values, 25)), 2),
                "P50": round(float(np.percentile(final_values, 50)), 2),
                "P75": round(float(np.percentile(final_values, 75)), 2),
                "P90": round(float(np.percentile(final_values, 90)), 2),
            },
            "assumed_daily_return_pct": round(daily_mu * 100, 4),
            "assumed_daily_volatility_pct": round(daily_sigma * 100, 4),
            "num_simulations": num_simulations,
        }, indent=2)

    @beta_tool
    def optimize_allocation(portfolio_name: str) -> str:
        """Use mean-variance optimisation to compute three portfolios on the efficient
        frontier: minimum variance, maximum Sharpe ratio (risk-free rate 4.5%), and
        equal weight. Returns the suggested weight for each asset in the portfolio.

        Requires historical price data.

        Args:
            portfolio_name: Name of the portfolio to optimise.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        try:
            rets = engine.calculate_returns(tickers)
        except Exception as e:
            return f"Could not load return data: {e}."

        if rets.empty:
            return "No price data available. Run 'invest-monitor collect' first."

        available = [t for t in tickers if t in rets.columns]
        if len(available) < 2:
            return "Need at least 2 assets with price history to optimise."

        rets = rets[available].dropna()
        mu = rets.mean().values * 252          # annualised expected returns
        cov = rets.cov().values * 252           # annualised covariance
        n = len(available)
        rf = 0.045

        def port_vol(w):
            return float(np.sqrt(w @ cov @ w))

        def neg_sharpe(w):
            ret = float(w @ mu)
            vol = port_vol(w)
            return -(ret - rf) / vol if vol > 0 else 0

        constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
        bounds = [(0.0, 1.0)] * n
        w0 = np.ones(n) / n

        # Min variance
        min_var_res = minimize(port_vol, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        # Max Sharpe
        max_sharpe_res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)

        def _portfolio_stats(w):
            ret = float(w @ mu)
            vol = port_vol(w)
            sharpe = (ret - rf) / vol if vol > 0 else 0
            return {"return_pct": round(ret * 100, 2), "volatility_pct": round(vol * 100, 2), "sharpe": round(sharpe, 3)}

        def _weights_dict(w):
            return {available[i]: round(float(w[i]) * 100, 1) for i in range(n)}

        equal_w = np.ones(n) / n
        result = {
            "portfolio": portfolio_name,
            "assets": available,
            "portfolios": {
                "equal_weight": {
                    "weights_pct": _weights_dict(equal_w),
                    "stats": _portfolio_stats(equal_w),
                },
                "minimum_variance": {
                    "weights_pct": _weights_dict(min_var_res.x),
                    "stats": _portfolio_stats(min_var_res.x),
                    "note": "Lowest possible volatility",
                },
                "maximum_sharpe": {
                    "weights_pct": _weights_dict(max_sharpe_res.x),
                    "stats": _portfolio_stats(max_sharpe_res.x),
                    "note": "Best risk-adjusted return (risk-free rate 4.5%)",
                },
            },
            "note": "Weights based on historical returns — past performance does not guarantee future results.",
        }
        return json.dumps(result, indent=2)

    @beta_tool
    def find_tax_loss_opportunities(portfolio_name: str, min_loss_pct: float = 5.0) -> str:
        """Identify positions with unrealised losses that exceed a minimum threshold,
        which could be candidates for tax-loss harvesting.  Also flags positions
        with large unrealised gains that may have tax implications if sold.

        Args:
            portfolio_name: Name of the portfolio.
            min_loss_pct: Minimum loss percentage to flag as a harvesting candidate (default 5%).
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as e:
            return str(e)

        tickers = [pos.asset.ticker for pos in portfolio.positions]
        latest = _latest_prices(tickers)

        loss_candidates = []
        gain_positions = []

        for pos in portfolio.positions:
            cost = pos.quantity * pos.cost_basis
            price = latest.get(pos.asset.ticker, pos.cost_basis)
            market = pos.quantity * price
            pnl = market - cost
            pnl_pct = pnl / cost * 100 if cost else 0

            entry = {
                "ticker": pos.asset.ticker,
                "name": pos.asset.name,
                "unrealised_pnl": round(pnl, 2),
                "return_pct": round(pnl_pct, 2),
                "cost_basis_total": round(cost, 2),
                "market_value": round(market, 2),
            }

            if pnl_pct <= -min_loss_pct:
                entry["harvest_note"] = (
                    f"Selling realises a ${abs(pnl):.2f} loss that can offset capital gains."
                )
                loss_candidates.append(entry)
            elif pnl_pct > 20:
                entry["gain_note"] = (
                    f"Unrealised gain of ${pnl:.2f} — consider tax implications before selling."
                )
                gain_positions.append(entry)

        loss_candidates.sort(key=lambda x: x["return_pct"])
        gain_positions.sort(key=lambda x: x["return_pct"], reverse=True)

        total_harvestable = sum(abs(p["unrealised_pnl"]) for p in loss_candidates)
        return json.dumps({
            "portfolio": portfolio_name,
            "min_loss_threshold_pct": min_loss_pct,
            "tax_loss_candidates": loss_candidates,
            "total_harvestable_loss": round(total_harvestable, 2),
            "large_gain_positions": gain_positions,
            "disclaimer": (
                "This is not tax advice. Consult a qualified tax advisor. "
                "Wash-sale rules may apply."
            ),
        }, indent=2)

    return [
        list_portfolios,
        get_portfolio_value,
        get_total_return,
        calculate_sharpe_ratio,
        get_diversification_score,
        suggest_rebalance,
        run_goal_projection,
        optimize_allocation,
        find_tax_loss_opportunities,
    ]

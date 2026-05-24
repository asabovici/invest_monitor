"""Portfolio Manager skills for the conversational PM agent.

These skills are deliberately distinct from the Risk / Wealth / Research
toolsets — they centre on the PM's core job: turning a market view into a
concrete, defensible trade proposal that the CIO can sign off on.

Skills:
    list_portfolios          — names available in the active data dir
    get_portfolio_snapshot   — current positions, weights, market value
    propose_trades           — convert a target allocation + $ amount into BUY/SELL orders
    compare_to_target        — current weight vs target weight per ticker (delta + verdict)
    estimate_sector_tilt     — sector-exposure delta from applying a proposed allocation
    summarise_proposal       — emit a clean structured proposal record (for later reference)
"""

from __future__ import annotations

import json
from typing import List

import pandas as pd
from anthropic import beta_tool

from src.agent.report_export import make_export_report_skill
from src.database import Database
from src.reporting import ReportingEngine


def create_pm_skills(db: Database, engine: ReportingEngine) -> List:
    """Return beta_tool-decorated PM skills bound to ``db`` / ``engine``."""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _latest_price(ticker: str, fallback: float = 0.0) -> float:
        prices = db.get_historical_prices([ticker])
        if prices.empty or ticker not in prices.columns:
            return fallback
        series = prices[ticker].dropna()
        return float(series.iloc[-1]) if not series.empty else fallback

    def _market_values(portfolio) -> tuple[float, dict[str, float], dict[str, float]]:
        """Return (total_value, {ticker: market_value}, {ticker: latest_price})."""
        values: dict[str, float] = {}
        prices: dict[str, float] = {}
        for pos in portfolio.positions:
            price = _latest_price(pos.asset.ticker, fallback=pos.cost_basis)
            prices[pos.asset.ticker] = price
            values[pos.asset.ticker] = pos.quantity * price
        total = sum(values.values())
        return total, values, prices

    def _parse_allocation(allocation_json: str) -> dict[str, float] | str:
        try:
            allocation = json.loads(allocation_json)
        except json.JSONDecodeError as exc:
            return f"Could not parse allocation_json: {exc}"
        if not isinstance(allocation, dict) or not allocation:
            return "allocation_json must be a non-empty JSON object like {\"AAPL\": 0.4, ...}"
        if not all(isinstance(v, (int, float)) for v in allocation.values()):
            return "All allocation weights must be numbers."
        total = sum(allocation.values())
        if total <= 0:
            return "Allocation weights must sum to a positive value."
        # Normalise so callers can pass either fractions (0.4) or percents (40).
        return {t: float(w) / total for t, w in allocation.items()}

    # ── Skills ────────────────────────────────────────────────────────────────

    @beta_tool
    def list_portfolios() -> str:
        """List all portfolios available in the database."""
        names = db.list_portfolios()
        if not names:
            return "No portfolios found."
        return "Available portfolios:\n" + "\n".join(f"  - {n}" for n in names)

    @beta_tool
    def get_portfolio_snapshot(portfolio_name: str) -> str:
        """Return current positions with weights and market value.

        PM-focused: this is the "what do we own right now?" view. No risk
        metrics — those belong to the Risk agent or the CIO.

        Args:
            portfolio_name: Name of the portfolio.
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as exc:
            return str(exc)
        if not portfolio.positions:
            return f"Portfolio '{portfolio_name}' has no positions."

        total, values, prices = _market_values(portfolio)
        rows = []
        for pos in portfolio.positions:
            t = pos.asset.ticker
            mv = values[t]
            weight = mv / total * 100 if total else 0.0
            rows.append({
                "ticker": t,
                "asset_type": pos.asset.asset_type.value,
                "sector": pos.asset.sector or "Unknown",
                "quantity": round(pos.quantity, 4),
                "cost_basis_per_share": round(pos.cost_basis, 4),
                "latest_price": round(prices[t], 4),
                "market_value": round(mv, 2),
                "weight_pct": round(weight, 2),
            })
        rows.sort(key=lambda r: -r["market_value"])
        df = pd.DataFrame(rows)
        return (
            f"Snapshot of '{portfolio_name}' (total market value ${total:,.2f}):\n"
            f"{df.to_string(index=False)}"
        )

    @beta_tool
    def propose_trades(
        portfolio_name: str,
        target_allocation_json: str,
        total_amount: float,
        rebalance_mode: str = "deploy",
    ) -> str:
        """Convert a target allocation + dollar amount into concrete BUY/SELL orders.

        Args:
            portfolio_name: Existing portfolio to base the proposal on.
            target_allocation_json: JSON dict mapping ticker → weight, e.g.
                '{"AAPL": 0.4, "MSFT": 0.3, "BND": 0.3}'. Weights can be
                fractions or percents — they're normalised to sum to 1.
            total_amount: Dollar capital to deploy ("deploy") or the total
                portfolio value to target ("rebalance"). Must be positive.
            rebalance_mode: "deploy" adds new capital on top of current holdings;
                "rebalance" treats total_amount as the desired total portfolio
                value and emits the trades that move current → target.
        """
        if total_amount <= 0:
            return "total_amount must be positive."
        if rebalance_mode not in ("deploy", "rebalance"):
            return "rebalance_mode must be 'deploy' or 'rebalance'."

        allocation = _parse_allocation(target_allocation_json)
        if isinstance(allocation, str):
            return allocation

        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as exc:
            return str(exc)

        _, current_mv, prices = _market_values(portfolio)

        if rebalance_mode == "deploy":
            target_dollars = {t: w * total_amount for t, w in allocation.items()}
            base_dollars = {t: 0.0 for t in allocation}  # only counting new BUYs
        else:  # rebalance
            target_dollars = {t: w * total_amount for t, w in allocation.items()}
            base_dollars = {t: current_mv.get(t, 0.0) for t in allocation}

        orders = []
        for t, target_dollar in target_dollars.items():
            delta = target_dollar - base_dollars[t]
            price = prices.get(t) or _latest_price(t, fallback=0.0)
            if price <= 0:
                orders.append({
                    "ticker": t,
                    "action": "SKIP",
                    "reason": "no recent price available — fetch first",
                    "dollar_change": round(delta, 2),
                })
                continue
            shares = delta / price
            orders.append({
                "ticker": t,
                "action": "BUY" if shares > 0 else ("SELL" if shares < 0 else "HOLD"),
                "shares": round(shares, 4),
                "price": round(price, 4),
                "dollar_change": round(delta, 2),
                "target_weight_pct": round(allocation[t] * 100, 2),
            })

        # In rebalance mode, also flag positions currently held but absent from
        # the target — those need to be liquidated.
        if rebalance_mode == "rebalance":
            for t, mv in current_mv.items():
                if t not in allocation and mv > 0:
                    price = prices.get(t, 0.0)
                    shares = -(mv / price) if price > 0 else 0.0
                    orders.append({
                        "ticker": t,
                        "action": "SELL",
                        "shares": round(shares, 4),
                        "price": round(price, 4),
                        "dollar_change": round(-mv, 2),
                        "target_weight_pct": 0.0,
                        "note": "not in target allocation — liquidate",
                    })

        df = pd.DataFrame(orders)
        header = (
            f"Proposed trades for '{portfolio_name}' "
            f"({rebalance_mode}, total_amount=${total_amount:,.2f})"
        )
        return f"{header}\n{df.to_string(index=False)}"

    @beta_tool
    def compare_to_target(portfolio_name: str, target_allocation_json: str) -> str:
        """Show current vs target weight per ticker with a delta and verdict.

        Args:
            portfolio_name: Portfolio to compare.
            target_allocation_json: JSON dict of ticker → target weight.
        """
        allocation = _parse_allocation(target_allocation_json)
        if isinstance(allocation, str):
            return allocation

        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as exc:
            return str(exc)

        total, current_mv, _ = _market_values(portfolio)
        if total <= 0:
            return f"Portfolio '{portfolio_name}' has no market value to compare."

        tickers = set(allocation) | set(current_mv)
        rows = []
        for t in sorted(tickers):
            current_pct = (current_mv.get(t, 0.0) / total * 100) if total else 0.0
            target_pct = allocation.get(t, 0.0) * 100
            delta = target_pct - current_pct
            verdict = "increase" if delta > 0.5 else ("decrease" if delta < -0.5 else "hold")
            rows.append({
                "ticker": t,
                "current_pct": round(current_pct, 2),
                "target_pct": round(target_pct, 2),
                "delta_pct": round(delta, 2),
                "verdict": verdict,
            })
        df = pd.DataFrame(rows)
        return f"Current vs target for '{portfolio_name}':\n{df.to_string(index=False)}"

    @beta_tool
    def estimate_sector_tilt(
        portfolio_name: str,
        target_allocation_json: str,
        total_amount: float,
    ) -> str:
        """Sector exposure before and after applying a proposed allocation.

        Treats ``total_amount`` as new capital deployed on top of the existing
        portfolio. Sector classification comes from each asset's stored sector.

        Args:
            portfolio_name: Existing portfolio.
            target_allocation_json: Proposed allocation (ticker → weight).
            total_amount: Dollar capital to deploy via the allocation.
        """
        if total_amount <= 0:
            return "total_amount must be positive."
        allocation = _parse_allocation(target_allocation_json)
        if isinstance(allocation, str):
            return allocation
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as exc:
            return str(exc)

        # Asset → sector lookup using the assets table for any candidates not
        # already held (so newly proposed tickers still get a sector if known).
        assets_df = db.get_all_assets() if hasattr(db, "get_all_assets") else pd.DataFrame()
        sector_lookup: dict[str, str] = {}
        if not assets_df.empty:
            for _, row in assets_df.iterrows():
                sector_lookup[row["ticker"]] = row.get("sector") or "Unknown"
        for pos in portfolio.positions:
            sector_lookup.setdefault(pos.asset.ticker, pos.asset.sector or "Unknown")

        total_before, current_mv, _ = _market_values(portfolio)
        before: dict[str, float] = {}
        for t, mv in current_mv.items():
            before[sector_lookup.get(t, "Unknown")] = before.get(sector_lookup.get(t, "Unknown"), 0.0) + mv

        proposed_dollars = {t: w * total_amount for t, w in allocation.items()}
        after = dict(before)
        for t, dollars in proposed_dollars.items():
            sec = sector_lookup.get(t, "Unknown")
            after[sec] = after.get(sec, 0.0) + dollars

        total_after = total_before + total_amount
        rows = []
        for sec in sorted(set(before) | set(after)):
            b_pct = (before.get(sec, 0.0) / total_before * 100) if total_before else 0.0
            a_pct = (after.get(sec, 0.0) / total_after * 100) if total_after else 0.0
            rows.append({
                "sector": sec,
                "before_pct": round(b_pct, 2),
                "after_pct": round(a_pct, 2),
                "delta_pct": round(a_pct - b_pct, 2),
            })
        df = pd.DataFrame(rows)
        return (
            f"Sector tilt for '{portfolio_name}' deploying ${total_amount:,.2f}:\n"
            f"{df.to_string(index=False)}"
        )

    @beta_tool
    def summarise_proposal(
        portfolio_name: str,
        target_allocation_json: str,
        total_amount: float,
        rationale: str,
    ) -> str:
        """Emit a clean structured proposal record for later reference.

        Use this once you've converged on a final proposal so it can be
        quoted verbatim or handed to the CIO. Returns both human-readable
        text and a JSON block.

        Args:
            portfolio_name: Target portfolio.
            target_allocation_json: Final allocation (ticker → weight).
            total_amount: Dollar amount being deployed / targeted.
            rationale: One- to three-sentence justification of the proposal.
        """
        allocation = _parse_allocation(target_allocation_json)
        if isinstance(allocation, str):
            return allocation
        record = {
            "portfolio": portfolio_name,
            "total_amount_usd": round(float(total_amount), 2),
            "allocation": {t: round(w, 4) for t, w in allocation.items()},
            "rationale": rationale.strip(),
        }
        weights_str = ", ".join(f"{t}={w*100:.1f}%" for t, w in record["allocation"].items())
        return (
            f"Proposal for '{portfolio_name}': deploy ${total_amount:,.2f} as "
            f"{weights_str}.\nRationale: {record['rationale']}\n\n"
            f"```json\n{json.dumps(record, indent=2)}\n```"
        )

    return [
        list_portfolios,
        get_portfolio_snapshot,
        propose_trades,
        compare_to_target,
        estimate_sector_tilt,
        summarise_proposal,
        make_export_report_skill(db, agent_kind="pm"),
    ]

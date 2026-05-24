"""CIO skills for the conversational CIO agent.

The CIO is the holistic-oversight agent: it doesn't build proposals, it
reviews them. Skills here support that mental model: get a top-down view of
a portfolio, score an incoming proposal, and produce one of three structured
decisions — approve, override, or request more research.

Skills:
    list_portfolios          — names available in the active data dir
    get_holistic_view        — value + top positions + sector concentration + risk headline
    review_proposal          — structural critique of a proposed allocation
    approve_proposal         — emit a formal sign-off record
    override_proposal        — replace a proposal with the CIO's version + reason
    request_more_research    — emit a brief for follow-up research
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List

import numpy as np
import pandas as pd
from anthropic import beta_tool

from src.agent.report_export import make_export_report_skill
from src.database import Database
from src.reporting import ReportingEngine


def create_cio_skills(db: Database, engine: ReportingEngine) -> List:
    """Return beta_tool-decorated CIO skills bound to ``db`` / ``engine``."""

    def _latest_price(ticker: str, fallback: float = 0.0) -> float:
        prices = db.get_historical_prices([ticker])
        if prices.empty or ticker not in prices.columns:
            return fallback
        series = prices[ticker].dropna()
        return float(series.iloc[-1]) if not series.empty else fallback

    def _market_values(portfolio):
        values: dict[str, float] = {}
        for pos in portfolio.positions:
            price = _latest_price(pos.asset.ticker, fallback=pos.cost_basis)
            values[pos.asset.ticker] = pos.quantity * price
        return sum(values.values()), values

    def _parse_allocation(allocation_json: str) -> dict[str, float] | str:
        try:
            allocation = json.loads(allocation_json)
        except json.JSONDecodeError as exc:
            return f"Could not parse allocation_json: {exc}"
        if not isinstance(allocation, dict) or not allocation:
            return "allocation_json must be a non-empty JSON object."
        if not all(isinstance(v, (int, float)) for v in allocation.values()):
            return "All allocation weights must be numbers."
        total = sum(allocation.values())
        if total <= 0:
            return "Allocation weights must sum to a positive value."
        return {t: float(w) / total for t, w in allocation.items()}

    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Skills ────────────────────────────────────────────────────────────────

    @beta_tool
    def list_portfolios() -> str:
        """List all portfolios available in the database."""
        names = db.list_portfolios()
        if not names:
            return "No portfolios found."
        return "Available portfolios:\n" + "\n".join(f"  - {n}" for n in names)

    @beta_tool
    def get_holistic_view(portfolio_name: str, top_n: int = 5) -> str:
        """Top-down view of a portfolio: value, top positions, sector mix, risk headline.

        Intended as the CIO's "single screen" — enough to form an opinion
        before drilling deeper or asking PM/Research for specifics.

        Args:
            portfolio_name: Portfolio to summarise.
            top_n: How many top positions to surface (default 5).
        """
        try:
            portfolio = db.get_portfolio(portfolio_name)
        except ValueError as exc:
            return str(exc)
        if not portfolio.positions:
            return f"Portfolio '{portfolio_name}' has no positions."

        total, values = _market_values(portfolio)
        sectors: dict[str, float] = {}
        for pos in portfolio.positions:
            sec = pos.asset.sector or "Unknown"
            sectors[sec] = sectors.get(sec, 0.0) + values[pos.asset.ticker]
        sector_rows = sorted(
            ((sec, v / total * 100 if total else 0.0) for sec, v in sectors.items()),
            key=lambda r: -r[1],
        )

        top_positions = sorted(
            (
                (pos.asset.ticker, values[pos.asset.ticker], values[pos.asset.ticker] / total * 100 if total else 0.0)
                for pos in portfolio.positions
            ),
            key=lambda r: -r[1],
        )[:top_n]

        # Risk headline — best-effort, falls back gracefully if no price history.
        risk_line = "Risk metrics unavailable (no price history)."
        try:
            metrics = engine.get_portfolio_risk_metrics(portfolio)
            vol = float(metrics["Volatility"]) * 100
            var = float(metrics["Historical VaR (95%)"]) * 100
            risk_line = (
                f"Annualised vol {vol:.2f}%, 95% historical VaR {var:.2f}% "
                f"(daily, weighted by cost-basis)."
            )
        except Exception:
            pass

        top_str = "\n".join(
            f"  - {t}: ${mv:,.2f}  ({pct:.1f}%)" for t, mv, pct in top_positions
        )
        sector_str = "\n".join(
            f"  - {sec}: {pct:.1f}%" for sec, pct in sector_rows
        )
        return (
            f"CIO view of '{portfolio_name}'\n"
            f"Total market value: ${total:,.2f}\n"
            f"{risk_line}\n\n"
            f"Top {len(top_positions)} positions:\n{top_str}\n\n"
            f"Sector concentration:\n{sector_str}"
        )

    @beta_tool
    def review_proposal(
        portfolio_name: str,
        target_allocation_json: str,
        total_amount: float,
        max_position_pct: float = 30.0,
        max_sector_pct: float = 40.0,
    ) -> str:
        """Score a proposed allocation against high-level CIO thresholds.

        Flags any per-position weight above ``max_position_pct`` (post-deploy)
        and any sector exposure above ``max_sector_pct``. Quantifies the
        sector-tilt change vs the current book.

        Args:
            portfolio_name: Existing portfolio.
            target_allocation_json: Proposal (ticker → weight).
            total_amount: Dollars deployed via the proposal.
            max_position_pct: Per-position concentration cap (post-deploy).
            max_sector_pct: Sector concentration cap (post-deploy).
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

        total_before, current_mv = _market_values(portfolio)
        proposed_dollars = {t: w * total_amount for t, w in allocation.items()}
        total_after = total_before + total_amount

        # Combined position-level weights post-deploy.
        combined: dict[str, float] = dict(current_mv)
        for t, dollars in proposed_dollars.items():
            combined[t] = combined.get(t, 0.0) + dollars
        position_flags = [
            (t, mv / total_after * 100)
            for t, mv in combined.items()
            if total_after and (mv / total_after * 100) > max_position_pct
        ]

        # Sector roll-up.
        sector_lookup: dict[str, str] = {}
        for pos in portfolio.positions:
            sector_lookup[pos.asset.ticker] = pos.asset.sector or "Unknown"
        assets_df = db.get_all_assets() if hasattr(db, "get_all_assets") else pd.DataFrame()
        if not assets_df.empty:
            for _, row in assets_df.iterrows():
                sector_lookup.setdefault(row["ticker"], row.get("sector") or "Unknown")

        before_sec: dict[str, float] = {}
        for t, mv in current_mv.items():
            before_sec[sector_lookup.get(t, "Unknown")] = before_sec.get(sector_lookup.get(t, "Unknown"), 0.0) + mv
        after_sec = dict(before_sec)
        for t, dollars in proposed_dollars.items():
            sec = sector_lookup.get(t, "Unknown")
            after_sec[sec] = after_sec.get(sec, 0.0) + dollars

        sector_flags = []
        sector_deltas = []
        for sec in sorted(set(before_sec) | set(after_sec)):
            b_pct = (before_sec.get(sec, 0.0) / total_before * 100) if total_before else 0.0
            a_pct = (after_sec.get(sec, 0.0) / total_after * 100) if total_after else 0.0
            sector_deltas.append((sec, b_pct, a_pct, a_pct - b_pct))
            if a_pct > max_sector_pct:
                sector_flags.append((sec, a_pct))

        delta_df = pd.DataFrame(sector_deltas, columns=["sector", "before_pct", "after_pct", "delta_pct"])
        delta_df = delta_df.round(2)

        flags_block = []
        if position_flags:
            flags_block.append("⚠ Per-position cap breached:")
            for t, pct in sorted(position_flags, key=lambda r: -r[1]):
                flags_block.append(f"   - {t} would be {pct:.1f}% (cap {max_position_pct:.0f}%)")
        if sector_flags:
            flags_block.append("⚠ Sector cap breached:")
            for sec, pct in sorted(sector_flags, key=lambda r: -r[1]):
                flags_block.append(f"   - {sec} would be {pct:.1f}% (cap {max_sector_pct:.0f}%)")
        if not flags_block:
            flags_block.append("✓ No CIO-level threshold breaches.")

        verdict = "REQUEST CHANGES" if (position_flags or sector_flags) else "PASSES CIO CHECKS"
        return (
            f"CIO review of proposal for '{portfolio_name}' "
            f"(deploy ${total_amount:,.2f}):\n\n"
            f"Sector tilt:\n{delta_df.to_string(index=False)}\n\n"
            + "\n".join(flags_block)
            + f"\n\nVerdict: {verdict}"
        )

    @beta_tool
    def approve_proposal(
        portfolio_name: str,
        target_allocation_json: str,
        total_amount: float,
        signoff_note: str,
    ) -> str:
        """Emit a formal CIO sign-off record. Does not execute trades.

        Args:
            portfolio_name: Portfolio the proposal applies to.
            target_allocation_json: The exact allocation being approved.
            total_amount: Dollars being deployed under this approval.
            signoff_note: One- to three-sentence rationale for the approval.
        """
        allocation = _parse_allocation(target_allocation_json)
        if isinstance(allocation, str):
            return allocation
        record = {
            "decision": "APPROVED",
            "portfolio": portfolio_name,
            "total_amount_usd": round(float(total_amount), 2),
            "allocation": {t: round(w, 4) for t, w in allocation.items()},
            "signoff_note": signoff_note.strip(),
            "decided_at": _utc_now_iso(),
        }
        return (
            f"CIO APPROVAL for '{portfolio_name}' (${total_amount:,.2f}).\n"
            f"Note: {record['signoff_note']}\n\n"
            f"```json\n{json.dumps(record, indent=2)}\n```\n"
            f"(No trades are executed — this is a sign-off record only.)"
        )

    @beta_tool
    def override_proposal(
        portfolio_name: str,
        original_allocation_json: str,
        override_allocation_json: str,
        total_amount: float,
        reason: str,
    ) -> str:
        """Replace a PM proposal with the CIO's version and record the reason.

        Args:
            portfolio_name: Portfolio the proposal applies to.
            original_allocation_json: The PM's proposed allocation.
            override_allocation_json: The CIO's replacement allocation.
            total_amount: Dollars being deployed under the override.
            reason: Why the CIO is overriding (one to three sentences).
        """
        orig = _parse_allocation(original_allocation_json)
        if isinstance(orig, str):
            return f"original_allocation_json: {orig}"
        override = _parse_allocation(override_allocation_json)
        if isinstance(override, str):
            return f"override_allocation_json: {override}"

        record = {
            "decision": "OVERRIDDEN",
            "portfolio": portfolio_name,
            "total_amount_usd": round(float(total_amount), 2),
            "original_allocation": {t: round(w, 4) for t, w in orig.items()},
            "override_allocation": {t: round(w, 4) for t, w in override.items()},
            "reason": reason.strip(),
            "decided_at": _utc_now_iso(),
        }
        return (
            f"CIO OVERRIDE for '{portfolio_name}'.\n"
            f"Reason: {record['reason']}\n\n"
            f"```json\n{json.dumps(record, indent=2)}\n```"
        )

    @beta_tool
    def request_more_research(question: str, scope: str = "general") -> str:
        """Emit a research brief the Researcher / human can act on.

        Use when a proposal is not approvable as-is because of a missing
        data point or analytical gap — not when it's just bad.

        Args:
            question: The specific question to be answered.
            scope: Free-text tag (e.g. "sector", "single-name", "macro").
        """
        record = {
            "decision": "MORE_RESEARCH_NEEDED",
            "question": question.strip(),
            "scope": scope.strip() or "general",
            "requested_at": _utc_now_iso(),
        }
        return (
            f"CIO REQUEST FOR MORE RESEARCH (scope={record['scope']}):\n"
            f"  {record['question']}\n\n"
            f"```json\n{json.dumps(record, indent=2)}\n```"
        )

    return [
        list_portfolios,
        get_holistic_view,
        review_proposal,
        approve_proposal,
        override_proposal,
        request_more_research,
        make_export_report_skill(db, agent_kind="cio"),
    ]

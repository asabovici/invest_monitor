"""Data-correction skills for the conversational data agent.

Every mutating skill here is a *proposal*: it returns a rendered diff and a
change id, and writes nothing. Only ``apply_change`` commits, and only when the
user has said so. Keeping that split visible in the tool surface — rather than
hiding it behind a single "fix it" tool — is what lets a human stay in the loop
on edits to real financial records.

Skills:
    scan_data                    — find integrity problems across all domains
    list_price_gaps              — missing business days for one ticker
    show_trades                  — the ledger, so corrections can cite a trade_id
    correct_trade                — fix a historical trade, replay the ledger
    insert_trade                 — add a missing historical trade, replay
    delete_trade                 — remove a trade that never happened, replay
    seed_opening_balance         — give an imported position a dated opening trade
    replay_ledger                — recompute positions from the ledger as-is
    fix_security_master          — patch columns on one assets row
    fill_prices_forward          — carry the last price across missing days
    correct_price                — fix or insert one price point
    normalise_fund_weights       — rescale a holdings snapshot to sum to 1
    review_pending               — staged changes awaiting approval
    apply_change / discard_change— commit or throw away a proposal
    show_audit_log               — what has already been applied
"""

from __future__ import annotations

from typing import List

from anthropic import beta_tool

from src.database import Database
from src.reporting import ReportingEngine
from src.services import datafix
from src.services.schemas.datafix import ChangePreview


def _fmt_preview(p: ChangePreview) -> str:
    """Render a staged change as a reviewable diff.

    The change id goes last and is stated as the explicit next action, because
    the most common failure mode for a tool-running model is to treat a preview
    as if it had already been applied.
    """
    lines = [
        f"PROPOSED ({p.domain}) — {p.summary}",
        f"target: {p.target}",
        f"rows: {p.rows_changed} changed, {p.rows_added} added, {p.rows_removed} removed",
        "",
    ]
    for c in p.changes:
        if not c.fields:
            lines.append(f"  {c.op:<6} {c.key}")
            continue
        detail = ", ".join(
            f"{f.field} {f.before} -> {f.after}"
            if f.before is not None
            else f"{f.field}={f.after}"
            for f in c.fields
        )
        lines.append(f"  {c.op:<6} {c.key}: {detail}")

    if p.warnings:
        lines.append("")
        lines.append("WARNINGS — show these to the user before they decide:")
        lines.extend(f"  ! {w}" for w in p.warnings)

    lines.append("")
    lines.append(
        f"NOTHING HAS BEEN WRITTEN. To commit: apply_change('{p.change_id}'). "
        f"To drop it: discard_change('{p.change_id}')."
    )
    return "\n".join(lines)


def create_data_skills(db: Database, engine: ReportingEngine) -> List:
    """Return beta_tool-decorated data-correction skills bound to ``db``.

    ``engine`` is unused today but kept in the signature so this factory
    matches the other five agents and can grow analytics-aware checks later.
    """
    data_dir = db.data_dir

    # ── Diagnosis ────────────────────────────────────────────────────────────

    @beta_tool
    def scan_data(portfolio_name: str = "") -> str:
        """Scan the database for data-integrity problems and return them worst-first.

        Checks positions (negative quantity, missing cost basis, tickers absent
        from the security master, portfolios missing from portfolios.parquet,
        drift against the trade ledger), the security master (missing fields,
        invalid asset_type), prices (absent history, interior gaps) and fund
        holdings (weights not summing to 1). Read-only.

        Args:
            portfolio_name: Restrict position checks to one portfolio. Empty = all.
        """
        report = datafix.scan_data_issues(data_dir, portfolio_name or None)
        if not report.issues:
            return "No data-integrity issues found."

        counts = ", ".join(f"{v} {k}" for k, v in sorted(report.counts.items()))
        lines = [f"Found {len(report.issues)} issue(s) — {counts}.", ""]
        for i in report.issues:
            fix = f"  [fix: {i.suggested_fix}]" if i.suggested_fix else ""
            lines.append(f"[{i.severity}] {i.domain} · {i.key}: {i.detail}{fix}")
        return "\n".join(lines)

    @beta_tool
    def list_price_gaps(ticker: str) -> str:
        """List runs of missing business days in a ticker's stored price history.

        Args:
            ticker: The ticker symbol to inspect.
        """
        try:
            gaps = datafix.find_price_gaps(data_dir, ticker)
        except ValueError as exc:
            return f"Error: {exc}"
        if not gaps:
            return f"{ticker}: no interior gaps in the stored price history."
        lines = [f"{ticker}: {len(gaps)} gap(s)."]
        lines += [f"  {g.start} -> {g.end} ({g.missing_days} business days)" for g in gaps]
        return "\n".join(lines)

    @beta_tool
    def show_trades(portfolio_name: str = "", ticker: str = "", limit: int = 25) -> str:
        """Show the trade ledger so a correction can cite a specific trade_id.

        Args:
            portfolio_name: Filter to one portfolio. Empty = all.
            ticker: Filter to one ticker. Empty = all.
            limit: Maximum rows to return, newest first.
        """
        df = db.list_trades(portfolio_name or None)
        if ticker:
            df = df[df["ticker"] == ticker]
        if df.empty:
            return "No trades match that filter."
        cols = ["trade_id", "portfolio_name", "ticker", "side", "quantity", "trade_price", "trade_date"]
        return df[cols].head(limit).to_string(index=False)

    # ── Positions, via the ledger ────────────────────────────────────────────

    @beta_tool
    def correct_trade(
        trade_id: int,
        quantity: float = 0.0,
        trade_price: float = 0.0,
        trade_date: str = "",
        side: str = "",
        ticker: str = "",
    ) -> str:
        """Propose a correction to a historical trade, replaying the ledger onto positions.

        This is the retroactive path: fix what was recorded, and let the current
        position fall out of a full replay so the ledger and the position agree.
        Only the fields you supply change. Returns a diff; writes nothing.

        Args:
            trade_id: Which trade to correct (see show_trades).
            quantity: Corrected quantity, always positive. 0 = leave unchanged.
            trade_price: Corrected per-share price. 0 = leave unchanged.
            trade_date: Corrected date, YYYY-MM-DD. Empty = leave unchanged.
            side: Corrected side, BUY or SELL. Empty = leave unchanged.
            ticker: Corrected ticker. Empty = leave unchanged.
        """
        try:
            return _fmt_preview(datafix.preview_trade_correction(
                data_dir,
                trade_id=trade_id,
                quantity=quantity or None,
                trade_price=trade_price or None,
                trade_date=trade_date or None,
                side=side or None,
                ticker=ticker or None,
            ))
        except ValueError as exc:
            return f"Error: {exc}"

    @beta_tool
    def insert_trade(
        portfolio_name: str,
        ticker: str,
        side: str,
        quantity: float,
        trade_price: float,
        trade_date: str,
    ) -> str:
        """Propose inserting a missing historical trade, replaying the ledger.

        The date places the trade correctly in history rather than appending it,
        so blended cost basis comes out right. Returns a diff; writes nothing.

        Args:
            portfolio_name: Portfolio the trade belongs to.
            ticker: Ticker traded.
            side: BUY or SELL.
            quantity: Always positive; direction comes from side.
            trade_price: Price per share.
            trade_date: Date of the trade, YYYY-MM-DD.
        """
        try:
            return _fmt_preview(datafix.preview_trade_insert(
                data_dir, portfolio_name, ticker, side, quantity, trade_price, trade_date
            ))
        except ValueError as exc:
            return f"Error: {exc}"

    @beta_tool
    def delete_trade(trade_id: int) -> str:
        """Propose removing a trade that never happened (duplicate or mis-entry), then replay.

        Args:
            trade_id: Which trade to remove (see show_trades).
        """
        try:
            return _fmt_preview(datafix.preview_trade_delete(data_dir, trade_id))
        except ValueError as exc:
            return f"Error: {exc}"

    @beta_tool
    def seed_opening_balance(
        portfolio_name: str,
        ticker: str,
        quantity: float,
        cost_basis: float,
        as_of_date: str,
    ) -> str:
        """Propose a dated opening trade for a position that has no trade history.

        Positions imported from a CSV have no ledger behind them. Recording the
        opening balance as a trade keeps the ledger authoritative and makes every
        later correction replayable.

        Args:
            portfolio_name: Portfolio holding the position.
            ticker: Ticker of the position.
            quantity: Opening quantity.
            cost_basis: Cost PER SHARE — never the total position cost.
            as_of_date: Date to record the opening balance, YYYY-MM-DD.
        """
        try:
            return _fmt_preview(datafix.preview_opening_balance(
                data_dir, portfolio_name, ticker, quantity, cost_basis, as_of_date
            ))
        except ValueError as exc:
            return f"Error: {exc}"

    @beta_tool
    def replay_ledger(portfolio_name: str) -> str:
        """Propose recomputing a portfolio's positions from its existing trades.

        Changes no trade — it shows how far stored positions have drifted from
        what the ledger implies. Tickers with no trades are left untouched.

        Args:
            portfolio_name: Portfolio to replay.
        """
        try:
            return _fmt_preview(datafix.preview_ledger_replay(data_dir, portfolio_name))
        except ValueError as exc:
            return f"Error: {exc}"

    # ── Security master ──────────────────────────────────────────────────────

    @beta_tool
    def fix_security_master(
        ticker: str,
        name: str = "",
        asset_type: str = "",
        sector: str = "",
        currency: str = "",
        income_rate: float = -1.0,
        payment_frequency: int = -1,
    ) -> str:
        """Propose patching named columns on one security-master row.

        Only the fields you supply change; everything else on the row is left
        alone. Returns a diff; writes nothing.

        Args:
            ticker: Which security to correct.
            name: Corrected display name. Empty = unchanged.
            asset_type: One of Stock, Bond, ETF, Fund, Cash, CD, Crypto. Empty = unchanged.
            sector: Corrected sector. Empty = unchanged.
            currency: Corrected currency code. Empty = unchanged.
            income_rate: Corrected annual income rate. Negative = unchanged.
            payment_frequency: Payments per year. Negative = unchanged.
        """
        try:
            return _fmt_preview(datafix.preview_asset_fix(
                data_dir,
                ticker,
                name=name or None,
                asset_type=asset_type or None,
                sector=sector or None,
                currency=currency or None,
                income_rate=None if income_rate < 0 else income_rate,
                payment_frequency=None if payment_frequency < 0 else payment_frequency,
            ))
        except ValueError as exc:
            return f"Error: {exc}"

    # ── Prices ───────────────────────────────────────────────────────────────

    @beta_tool
    def fill_prices_forward(
        ticker: str, through_date: str = "", max_run_days: int = 30
    ) -> str:
        """Propose carrying the last known price forward across missing business days.

        Fills interior gaps, and extends to through_date when given. Refuses runs
        longer than max_run_days, because a long flat carry understates measured
        volatility and drawdown.

        Args:
            ticker: Ticker to fill.
            through_date: Extend the series to this date, YYYY-MM-DD. Empty = only interior gaps.
            max_run_days: Largest single carried run allowed, in business days.
        """
        try:
            return _fmt_preview(datafix.preview_price_fill_forward(
                data_dir, ticker, through_date or None, max_run_days
            ))
        except ValueError as exc:
            return f"Error: {exc}"

    @beta_tool
    def correct_price(ticker: str, date: str, price: float) -> str:
        """Propose correcting or inserting a single price point (a bad tick).

        Args:
            ticker: Ticker to correct.
            date: Date of the price, YYYY-MM-DD.
            price: Corrected price.
        """
        try:
            return _fmt_preview(datafix.preview_price_correction(data_dir, ticker, date, price))
        except ValueError as exc:
            return f"Error: {exc}"

    # ── Fund holdings ────────────────────────────────────────────────────────

    @beta_tool
    def normalise_fund_weights(fund_ticker: str, as_of_date: str = "") -> str:
        """Propose rescaling a fund's holdings snapshot so its weights sum to 1.

        Args:
            fund_ticker: The fund or ETF.
            as_of_date: Snapshot date, YYYY-MM-DD. Empty = latest snapshot.
        """
        try:
            return _fmt_preview(datafix.preview_normalise_fund_weights(
                data_dir, fund_ticker, as_of_date or None
            ))
        except ValueError as exc:
            return f"Error: {exc}"

    # ── Approval gate ────────────────────────────────────────────────────────

    @beta_tool
    def review_pending() -> str:
        """List every proposed change still awaiting approval."""
        staged = datafix.list_staged()
        if not staged:
            return "No changes are pending."
        return "\n".join(
            f"{p.change_id}  [{p.domain}] {p.summary} "
            f"({p.rows_changed}c/{p.rows_added}a/{p.rows_removed}d)"
            + (f"  WARNINGS: {len(p.warnings)}" if p.warnings else "")
            for p in staged
        )

    @beta_tool
    def apply_change(change_id: str) -> str:
        """Commit a proposed change. Only call this after the user has approved it.

        Backs up every affected file first and appends to the audit log. A change
        can only be applied once.

        Args:
            change_id: The id from the proposal you are committing.
        """
        try:
            r = datafix.apply_change(change_id)
        except ValueError as exc:
            return f"Error: {exc}"
        return (
            f"APPLIED {r.change_id} — {r.summary}\n"
            f"  rows written: {r.rows_written}\n"
            f"  backup: {r.backup_path}\n"
            f"  audit:  {r.audit_path}"
        )

    @beta_tool
    def discard_change(change_id: str) -> str:
        """Throw away a proposed change without applying it.

        Args:
            change_id: The proposal to discard.
        """
        try:
            datafix.discard_change(change_id)
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Discarded {change_id}. Nothing was written."

    @beta_tool
    def show_audit_log(limit: int = 10) -> str:
        """Show recently applied corrections, newest first.

        Args:
            limit: How many entries to return.
        """
        entries = datafix.read_audit_log(data_dir, limit)
        if not entries:
            return "No corrections have been applied yet."
        return "\n".join(
            f"{e['timestamp'][:19]}  [{e['domain']}] {e['summary']} "
            f"({e['rows_written']} rows, backup {e['backup']})"
            for e in entries
        )

    return [
        scan_data,
        list_price_gaps,
        show_trades,
        correct_trade,
        insert_trade,
        delete_trade,
        seed_opening_balance,
        replay_ledger,
        fix_security_master,
        fill_prices_forward,
        correct_price,
        normalise_fund_weights,
        review_pending,
        apply_change,
        discard_change,
        show_audit_log,
    ]

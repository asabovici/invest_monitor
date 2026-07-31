"""Data-correction service — retroactive fixes with a preview/apply gate.

This is the only service in the layer whose whole purpose is to *mutate*
existing records, so it is deliberately more defensive than its neighbours.
Three rules shape the design:

1. **Nothing writes without a preview.** Every mutating entry point is a
   ``preview_*`` function that computes a diff, stages it, and returns a
   :class:`ChangePreview`. Only :func:`apply_change` touches disk. An LLM
   proposing an edit and a human approving it are then separate steps, which
   is what makes agent-driven correction of financial records safe.

2. **The trade ledger is the source of truth for positions.** Positions carry
   no time dimension, so a retroactive position fix is expressed as a fix to a
   dated trade followed by a full replay of that portfolio's ledger. Editing
   ``positions.parquet`` by hand would leave the ledger disagreeing with the
   position and destroy the audit trail.

3. **``cost_basis`` is per share, always.** Storing a total here causes
   double-multiplication in ``Portfolio.total_cost()``. :func:`_replay_ledger`
   reproduces ``Database._apply_trade_to_positions`` exactly (average-cost
   blending on buys, quantity-only reduction on sells) and the scan flags rows
   that smell like a total was stored instead.

Callers get a backup and an audit line for free on every apply.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

from src.models import AssetType
from src.services._db import _get_db
from src.services.schemas.datafix import (
    ApplyResult,
    ChangePreview,
    FieldChange,
    FixDomain,
    Issue,
    PriceGap,
    RowChange,
    ScanReport,
)

BACKUP_DIR = ".backups"
AUDIT_FILE = "audit_log.jsonl"

# A fill-forward run longer than this is reported as a warning: carrying a
# stale price for weeks silently flatters volatility and drawdown figures.
LONG_FILL_DAYS = 7


# ── Staged-change cache ──────────────────────────────────────────────────────
#
# Process-local, like the session caches in ``agents.py`` / ``trading_graph.py``.
# Previews are cheap to regenerate, so losing them on restart is harmless — and
# far safer than persisting an approved-but-unapplied write.


@dataclass
class _Staged:
    preview: ChangePreview
    data_dir: str
    # Files this change will touch, relative to data_dir — backed up before write.
    touches: list[str]
    apply_fn: Callable[[], int]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_staged: dict[str, _Staged] = {}


def reset_staged() -> None:
    """Drop all staged changes (tests call this between cases)."""
    _staged.clear()


def list_staged() -> list[ChangePreview]:
    """Every change awaiting approval, oldest first."""
    return [s.preview for s in sorted(_staged.values(), key=lambda s: s.created_at)]


def discard_change(change_id: str) -> None:
    """Throw away a staged change without applying it."""
    if change_id not in _staged:
        raise ValueError(f"Change {change_id!r} not found.")
    del _staged[change_id]


def _stage(
    domain: FixDomain,
    data_dir: str,
    summary: str,
    target: str,
    changes: list[RowChange],
    touches: list[str],
    apply_fn: Callable[[], int],
    warnings: list[str] | None = None,
) -> ChangePreview:
    change_id = f"chg_{uuid.uuid4().hex[:6]}"
    preview = ChangePreview(
        change_id=change_id,
        domain=domain,
        summary=summary,
        target=target,
        rows_changed=sum(1 for c in changes if c.op == "update"),
        rows_added=sum(1 for c in changes if c.op == "insert"),
        rows_removed=sum(1 for c in changes if c.op == "delete"),
        changes=changes,
        warnings=warnings or [],
    )
    _staged[change_id] = _Staged(
        preview=preview, data_dir=data_dir, touches=touches, apply_fn=apply_fn
    )
    return preview


# ── Apply / backup / audit ───────────────────────────────────────────────────


def apply_change(change_id: str) -> ApplyResult:
    """Commit a staged change, after backing up every file it touches.

    Raises ``ValueError`` if the id is unknown (including after a prior apply —
    changes are single-use so an approval can't be silently replayed).
    """
    staged = _staged.get(change_id)
    if staged is None:
        raise ValueError(f"Change {change_id!r} not found.")

    backup_path = _backup(staged.data_dir, staged.touches)
    rows = staged.apply_fn()
    audit_path = _audit(staged, backup_path, rows)

    # Single-use: drop it so the same approval cannot be applied twice.
    del _staged[change_id]

    return ApplyResult(
        change_id=change_id,
        domain=staged.preview.domain,
        summary=staged.preview.summary,
        backup_path=backup_path,
        audit_path=audit_path,
        rows_written=rows,
    )


def _backup(data_dir: str, rel_paths: list[str]) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_root = os.path.join(data_dir, BACKUP_DIR, stamp)
    os.makedirs(dest_root, exist_ok=True)
    for rel in rel_paths:
        src = os.path.join(data_dir, rel)
        if not os.path.exists(src):
            continue
        dest = os.path.join(dest_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
    return dest_root


def _audit(staged: _Staged, backup_path: str, rows: int) -> str:
    path = os.path.join(staged.data_dir, AUDIT_FILE)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "change_id": staged.preview.change_id,
        "domain": staged.preview.domain,
        "target": staged.preview.target,
        "summary": staged.preview.summary,
        "rows_written": rows,
        "backup": backup_path,
        "changes": [c.model_dump() for c in staged.preview.changes],
    }
    with open(path, "a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    return path


def read_audit_log(data_dir: str, limit: int = 20) -> list[dict]:
    """Most recent audit entries, newest first."""
    path = os.path.join(data_dir, AUDIT_FILE)
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    out = []
    for ln in reversed(lines[-limit:]):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


# ── Ledger replay (the mechanism for retroactive position fixes) ─────────────


def _replay_ledger(trades: pd.DataFrame, portfolio_name: str) -> dict[str, dict]:
    """Recompute positions for one portfolio from its trades, in date order.

    Mirrors ``Database._apply_trade_to_positions`` exactly so a replay of an
    unmodified ledger is a no-op: buys blend average cost, sells reduce
    quantity while leaving cost basis alone, and a position that sells down to
    zero disappears. Divergence here would silently rewrite correct data, so
    this stays in lockstep with the Database implementation.
    """
    df = trades[trades["portfolio_name"] == portfolio_name].copy()
    if df.empty:
        return {}

    df["_d"] = pd.to_datetime(df["trade_date"], errors="coerce")
    # trade_id breaks ties so same-day trades replay in the order recorded.
    df = df.sort_values(["_d", "trade_id"], kind="stable")

    book: dict[str, dict] = {}
    for _, r in df.iterrows():
        ticker = str(r["ticker"])
        qty = float(r["quantity"])
        price = float(r["trade_price"])
        side = str(r["side"]).upper()

        if side == "BUY":
            if ticker not in book:
                book[ticker] = {"quantity": qty, "cost_basis": price}
            else:
                old_q = book[ticker]["quantity"]
                old_c = book[ticker]["cost_basis"]
                new_q = old_q + qty
                book[ticker] = {
                    "quantity": new_q,
                    "cost_basis": round((old_q * old_c + qty * price) / new_q, 6),
                }
        else:  # SELL
            if ticker in book:
                new_q = book[ticker]["quantity"] - qty
                if new_q <= 1e-8:
                    del book[ticker]
                else:
                    book[ticker]["quantity"] = new_q
    return book


def _ledger_tickers(trades: pd.DataFrame, portfolio_name: str) -> set[str]:
    """Tickers the ledger has any record of for this portfolio."""
    df = trades[trades["portfolio_name"] == portfolio_name]
    return set(df["ticker"].astype(str)) if not df.empty else set()


def _merge_untracked(
    current: pd.DataFrame,
    portfolio_name: str,
    book: dict[str, dict],
    ledger_tickers: set[str],
) -> dict[str, dict]:
    """Combine a replayed book with positions the ledger says nothing about.

    Positions imported from a CSV have no trades behind them. A naive replay
    writes only what the ledger produced, which silently deletes every one of
    those imported rows — the single most destructive thing this module could
    do. So the ledger is treated as authoritative *only for tickers it covers*:
    a ticker with trades is fully governed by the replay (including selling
    down to zero, which correctly removes it), while a ticker with no trades is
    left exactly as it is.
    """
    cur = current[current["portfolio_name"] == portfolio_name]
    merged = {
        str(r["ticker"]): {
            "quantity": float(r["quantity"]),
            "cost_basis": float(r["cost_basis"]),
        }
        for _, r in cur.iterrows()
        if str(r["ticker"]) not in ledger_tickers
    }
    merged.update(book)
    return merged


def _replayed_positions(
    data_dir: str, trades: pd.DataFrame, portfolio_name: str
) -> tuple[dict[str, dict], pd.DataFrame, list[RowChange]]:
    """Replay ``trades`` and diff the result against what is stored on disk."""
    book = _replay_ledger(trades, portfolio_name)
    merged = _merge_untracked(
        pd.read_parquet(os.path.join(data_dir, "positions.parquet")),
        portfolio_name,
        book,
        _ledger_tickers(trades, portfolio_name),
    )
    positions = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    return merged, positions, _positions_diff(positions, portfolio_name, merged)


def _positions_diff(
    current: pd.DataFrame, portfolio_name: str, book: dict[str, dict]
) -> list[RowChange]:
    """Row-level diff between stored positions and a replayed book."""
    cur = current[current["portfolio_name"] == portfolio_name]
    cur_map = {
        str(r["ticker"]): {
            "quantity": float(r["quantity"]),
            "cost_basis": float(r["cost_basis"]),
        }
        for _, r in cur.iterrows()
    }

    changes: list[RowChange] = []
    for ticker in sorted(set(cur_map) | set(book)):
        key = f"{portfolio_name} / {ticker}"
        before = cur_map.get(ticker)
        after = book.get(ticker)

        if before is None:
            changes.append(RowChange(key=key, op="insert", fields=[
                FieldChange(field="quantity", after=after["quantity"]),
                FieldChange(field="cost_basis", after=after["cost_basis"]),
            ]))
        elif after is None:
            changes.append(RowChange(key=key, op="delete", fields=[
                FieldChange(field="quantity", before=before["quantity"]),
                FieldChange(field="cost_basis", before=before["cost_basis"]),
            ]))
        else:
            fields = [
                FieldChange(field=f, before=before[f], after=after[f])
                for f in ("quantity", "cost_basis")
                if not np.isclose(before[f], after[f], rtol=1e-9, atol=1e-9)
            ]
            if fields:
                changes.append(RowChange(key=key, op="update", fields=fields))
    return changes


def _replay_risks(changes: list[RowChange]) -> list[str]:
    """Ways a straight ledger replay could corrupt rather than repair positions.

    ``_merge_untracked`` protects tickers the ledger has never heard of, but a
    ticker with *partial* coverage — a few recent trades recorded on top of a
    position imported from a CSV — is still fully governed by the replay. Two
    shapes matter, and both mean "the ledger is incomplete or double-counted",
    not "the position is wrong":

    - **Reductions and removals**: the replay discards every share that predates
      the ledger.
    - **Insertions**: the ledger claims a holding the positions table does not
      have. Usually a duplicate entry or a half-finished ticker rename, so
      applying it inflates the portfolio instead of shrinking it.

    Only call this for a *pure* replay. ``preview_trade_insert`` legitimately
    produces an insertion, and flagging that would be noise.
    """
    out = []
    for c in changes:
        if c.op == "delete":
            qty = next((f.before for f in c.fields if f.field == "quantity"), None)
            out.append(f"{c.key}: replay removes the position entirely (held {qty})")
            continue
        if c.op == "insert":
            qty = next((f.after for f in c.fields if f.field == "quantity"), None)
            out.append(
                f"{c.key}: replay ADDS a position of {qty} that the positions "
                "table does not have — likely a duplicate trade or a ticker "
                "rename recorded on only one side"
            )
            continue
        for f in c.fields:
            if f.field != "quantity" or f.before is None or f.after is None:
                continue
            try:
                before, after = float(f.before), float(f.after)
            except (TypeError, ValueError):
                continue
            if after < before * 0.99:
                out.append(
                    f"{c.key}: replay reduces quantity {before:g} -> {after:g} "
                    f"({before - after:g} shares unaccounted for in the ledger)"
                )
    return out


def _cost_basis_warnings(changes: list[RowChange]) -> list[str]:
    """Flag cost-basis moves large enough to look like a units mistake.

    The April 2026 bug stored a *total* where a per-share value belonged, which
    shows up as a jump of roughly the position's quantity. Surfacing it as a
    warning keeps the reviewer from rubber-stamping the same class of error.
    """
    out = []
    for c in changes:
        for f in c.fields:
            if f.field != "cost_basis" or f.before in (None, 0) or f.after is None:
                continue
            try:
                ratio = float(f.after) / float(f.before)
            except (TypeError, ZeroDivisionError):
                continue
            if ratio > 10 or ratio < 0.1:
                out.append(
                    f"{c.key}: cost_basis changes by {ratio:.1f}x "
                    f"({f.before} -> {f.after}). cost_basis is PER SHARE — "
                    "check this isn't a total-vs-per-share mix-up."
                )
    return out


def _write_positions(data_dir: str, portfolio_name: str, book: dict[str, dict]) -> int:
    db = _get_db(data_dir)
    rows = [
        {"ticker": t, "quantity": v["quantity"], "cost_basis": v["cost_basis"]}
        for t, v in sorted(book.items())
    ]
    db.update_positions_direct(portfolio_name, rows)
    return len(rows)


def _require_portfolio(data_dir: str, name: str) -> None:
    if name not in _get_db(data_dir).list_portfolios():
        raise ValueError(f"Portfolio {name!r} not found.")


def _load_trades(data_dir: str) -> pd.DataFrame:
    return _get_db(data_dir).list_trades()


# ── Positions: retroactive correction via the ledger ─────────────────────────


def preview_trade_correction(
    data_dir: str,
    trade_id: int,
    quantity: float | None = None,
    trade_price: float | None = None,
    trade_date: str | None = None,
    side: str | None = None,
    ticker: str | None = None,
) -> ChangePreview:
    """Correct a historical trade, then replay the ledger onto positions.

    This is the retroactive path: fix what was actually recorded on the day it
    happened and let the position fall out of the replay, so the ledger and the
    position never disagree.

    Raises ``ValueError`` if the trade does not exist or a field is invalid.
    """
    trades = _load_trades(data_dir)
    if trades.empty or trade_id not in set(trades["trade_id"].astype(int)):
        raise ValueError(f"Trade {trade_id} not found.")

    updated = trades.copy()
    updated["trade_id"] = updated["trade_id"].astype(int)
    mask = updated["trade_id"] == trade_id
    row = updated[mask].iloc[0]
    portfolio_name = str(row["portfolio_name"])

    edits: list[FieldChange] = []
    for fname, value in (
        ("quantity", quantity),
        ("trade_price", trade_price),
        ("trade_date", trade_date),
        ("side", side),
        ("ticker", ticker),
    ):
        if value is None:
            continue
        if fname in ("quantity", "trade_price") and float(value) <= 0:
            raise ValueError(f"{fname} must be positive (quantity is always positive; use side).")
        if fname == "side":
            value = str(value).upper()
            if value not in ("BUY", "SELL"):
                raise ValueError("side must be 'BUY' or 'SELL'.")
        before = row[fname]
        if str(before) == str(value):
            continue
        updated.loc[mask, fname] = value
        edits.append(FieldChange(field=fname, before=before, after=value))

    if not edits:
        raise ValueError("No changes requested — every supplied field already matches.")

    merged, _, pos_changes = _replayed_positions(data_dir, updated, portfolio_name)

    trade_change = RowChange(key=f"trade {trade_id}", op="update", fields=edits)
    all_changes = [trade_change] + pos_changes

    def _apply() -> int:
        updated.drop(columns=[c for c in updated.columns if c.startswith("_")], errors="ignore") \
            .to_parquet(os.path.join(data_dir, "trades.parquet"), index=False)
        return 1 + _write_positions(data_dir, portfolio_name, merged)

    return _stage(
        domain="trades",
        data_dir=data_dir,
        summary=f"Correct trade {trade_id} and replay '{portfolio_name}' ledger",
        target=portfolio_name,
        changes=all_changes,
        touches=["trades.parquet", "positions.parquet"],
        apply_fn=_apply,
        warnings=_cost_basis_warnings(pos_changes) + _replay_risks(pos_changes),
    )


def preview_trade_insert(
    data_dir: str,
    portfolio_name: str,
    ticker: str,
    side: str,
    quantity: float,
    trade_price: float,
    trade_date: str,
) -> ChangePreview:
    """Insert a missing historical trade and replay.

    Use this for a trade that happened but was never recorded — the date
    places it correctly in history rather than appending it to the end.
    """
    _require_portfolio(data_dir, portfolio_name)
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be 'BUY' or 'SELL'.")
    if quantity <= 0 or trade_price <= 0:
        raise ValueError("quantity and trade_price must both be positive.")

    trades = _load_trades(data_dir)
    next_id = int(trades["trade_id"].max()) + 1 if not trades.empty else 1
    new_row = pd.DataFrame([{
        "trade_id": next_id,
        "portfolio_name": portfolio_name,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "trade_price": trade_price,
        "trade_date": trade_date,
    }])
    updated = pd.concat([trades, new_row], ignore_index=True)

    merged, _, pos_changes = _replayed_positions(data_dir, updated, portfolio_name)

    trade_change = RowChange(key=f"trade {next_id} (new)", op="insert", fields=[
        FieldChange(field="ticker", after=ticker),
        FieldChange(field="side", after=side),
        FieldChange(field="quantity", after=quantity),
        FieldChange(field="trade_price", after=trade_price),
        FieldChange(field="trade_date", after=trade_date),
    ])

    def _apply() -> int:
        updated.to_parquet(os.path.join(data_dir, "trades.parquet"), index=False)
        return 1 + _write_positions(data_dir, portfolio_name, merged)

    return _stage(
        domain="trades",
        data_dir=data_dir,
        summary=(
            f"Insert {side} {quantity} x {ticker} @ {trade_price} on {trade_date} "
            f"into '{portfolio_name}' and replay"
        ),
        target=portfolio_name,
        changes=[trade_change] + pos_changes,
        touches=["trades.parquet", "positions.parquet"],
        apply_fn=_apply,
        warnings=_cost_basis_warnings(pos_changes),
    )


def preview_trade_delete(data_dir: str, trade_id: int) -> ChangePreview:
    """Remove a trade that never happened (duplicate or mis-entry) and replay."""
    trades = _load_trades(data_dir)
    trades["trade_id"] = trades["trade_id"].astype(int)
    if trades.empty or trade_id not in set(trades["trade_id"]):
        raise ValueError(f"Trade {trade_id} not found.")

    row = trades[trades["trade_id"] == trade_id].iloc[0]
    portfolio_name = str(row["portfolio_name"])
    updated = trades[trades["trade_id"] != trade_id].copy()

    merged, _, pos_changes = _replayed_positions(data_dir, updated, portfolio_name)

    trade_change = RowChange(key=f"trade {trade_id}", op="delete", fields=[
        FieldChange(field="ticker", before=row["ticker"]),
        FieldChange(field="side", before=row["side"]),
        FieldChange(field="quantity", before=row["quantity"]),
        FieldChange(field="trade_price", before=row["trade_price"]),
        FieldChange(field="trade_date", before=row["trade_date"]),
    ])

    def _apply() -> int:
        updated.to_parquet(os.path.join(data_dir, "trades.parquet"), index=False)
        return 1 + _write_positions(data_dir, portfolio_name, merged)

    return _stage(
        domain="trades",
        data_dir=data_dir,
        summary=f"Delete trade {trade_id} from '{portfolio_name}' and replay",
        target=portfolio_name,
        changes=[trade_change] + pos_changes,
        touches=["trades.parquet", "positions.parquet"],
        apply_fn=_apply,
        warnings=_cost_basis_warnings(pos_changes) + _replay_risks(pos_changes),
    )


def preview_opening_balance(
    data_dir: str,
    portfolio_name: str,
    ticker: str,
    quantity: float,
    cost_basis: float,
    as_of_date: str,
) -> ChangePreview:
    """Seed a dated opening trade for a position that has no trade history.

    Positions imported from a CSV have no ledger behind them, so a replay would
    wipe them. Rather than hand-editing the position — which would leave the
    ledger permanently disagreeing — this records the opening balance *as a
    trade*, keeping the ledger authoritative and every later correction
    replayable.

    ``cost_basis`` is per share.
    """
    _require_portfolio(data_dir, portfolio_name)
    if quantity <= 0 or cost_basis <= 0:
        raise ValueError("quantity and cost_basis must both be positive.")

    trades = _load_trades(data_dir)
    existing = trades[
        (trades["portfolio_name"] == portfolio_name) & (trades["ticker"] == ticker)
    ]
    warnings = []
    if not existing.empty:
        warnings.append(
            f"{ticker} already has {len(existing)} trade(s) in '{portfolio_name}'. "
            "An opening balance on top will blend with them — correct the existing "
            "trades instead if that is not what you want."
        )

    preview = preview_trade_insert(
        data_dir=data_dir,
        portfolio_name=portfolio_name,
        ticker=ticker,
        side="BUY",
        quantity=quantity,
        trade_price=cost_basis,
        trade_date=as_of_date,
    )
    preview.summary = (
        f"Seed opening balance {quantity} x {ticker} @ {cost_basis}/share "
        f"in '{portfolio_name}' as of {as_of_date}"
    )
    preview.warnings.extend(warnings)
    return preview


def preview_ledger_replay(data_dir: str, portfolio_name: str) -> ChangePreview:
    """Recompute positions from the existing ledger without changing any trade.

    Useful after a direct edit elsewhere has left positions out of step with
    the ledger — it shows exactly how far they have drifted.
    """
    _require_portfolio(data_dir, portfolio_name)
    trades = _load_trades(data_dir)
    merged, _, changes = _replayed_positions(data_dir, trades, portfolio_name)

    if not changes:
        raise ValueError(
            f"Positions for {portfolio_name!r} already match the ledger — nothing to replay."
        )

    warnings = _cost_basis_warnings(changes)
    risks = _replay_risks(changes)
    if risks:
        warnings.append(
            "DESTRUCTIVE — this replay does not just adjust values, it changes what "
            "you hold. That usually means the ledger is incomplete or double-counted "
            "rather than that the positions are wrong. Reconcile the ledger with "
            "insert_trade / seed_opening_balance instead, unless you are certain the "
            "ledger is a complete record."
        )
        warnings.extend(risks)

    def _apply() -> int:
        return _write_positions(data_dir, portfolio_name, merged)

    return _stage(
        domain="positions",
        data_dir=data_dir,
        summary=f"Replay '{portfolio_name}' ledger onto positions",
        target=portfolio_name,
        changes=changes,
        touches=["positions.parquet"],
        apply_fn=_apply,
        warnings=warnings,
    )


# ── Security master ──────────────────────────────────────────────────────────

_ASSET_FIELDS = ("name", "asset_type", "sector", "currency", "income_rate", "payment_frequency")


def preview_asset_fix(data_dir: str, ticker: str, **fields) -> ChangePreview:
    """Patch named columns on one security-master row.

    Field-level by design: ``Database.update_assets_direct`` overwrites the
    entire assets table, which is far too blunt to hand to an agent. Only the
    columns named here move.

    Raises ``ValueError`` for an unknown ticker, an unknown column, or an
    ``asset_type`` outside the enum.
    """
    supplied = {k: v for k, v in fields.items() if v is not None}
    if not supplied:
        raise ValueError("No fields supplied to change.")

    unknown = [k for k in supplied if k not in _ASSET_FIELDS]
    if unknown:
        raise ValueError(f"Unknown asset fields: {unknown}. Valid: {list(_ASSET_FIELDS)}")

    if "asset_type" in supplied:
        try:
            AssetType(supplied["asset_type"])
        except ValueError as exc:
            valid = [t.value for t in AssetType]
            raise ValueError(
                f"Invalid asset_type {supplied['asset_type']!r}. Valid: {valid}"
            ) from exc

    db = _get_db(data_dir)
    assets = db.get_all_assets()
    mask = assets["ticker"] == ticker
    if not mask.any():
        raise ValueError(f"Ticker {ticker!r} not found in the security master.")

    row = assets[mask].iloc[0]
    edits = [
        FieldChange(field=k, before=row.get(k), after=v)
        for k, v in supplied.items()
        if str(row.get(k)) != str(v)
    ]
    if not edits:
        raise ValueError("No changes — every supplied field already matches.")

    updated = assets.copy()
    for k, v in supplied.items():
        updated.loc[mask, k] = v

    def _apply() -> int:
        db.update_assets_direct(updated)
        return 1

    return _stage(
        domain="assets",
        data_dir=data_dir,
        summary=f"Update security master for {ticker}",
        target=ticker,
        changes=[RowChange(key=ticker, op="update", fields=edits)],
        touches=["assets.parquet"],
        apply_fn=_apply,
    )


# ── Prices ───────────────────────────────────────────────────────────────────


def _price_path(data_dir: str, ticker: str) -> str:
    return os.path.join(data_dir, "prices", f"{ticker}.parquet")


def _load_prices(data_dir: str, ticker: str) -> pd.DataFrame:
    path = _price_path(data_dir, ticker)
    if not os.path.exists(path):
        raise ValueError(f"No price history found for {ticker!r}.")
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def find_price_gaps(data_dir: str, ticker: str, min_days: int = 1) -> list[PriceGap]:
    """Runs of missing business days inside a ticker's stored history.

    Only interior gaps are reported — a series simply ending early is a
    staleness question, handled by :func:`preview_price_fill_forward`.
    """
    df = _load_prices(data_dir, ticker)
    if df.empty:
        return []

    full = pd.date_range(df.index.min(), df.index.max(), freq="B")
    missing = full.difference(df.index)
    if len(missing) == 0:
        return []

    gaps: list[PriceGap] = []
    run_start = prev = missing[0]
    for d in missing[1:]:
        # A break of more than 1 business day ends the current run.
        if (d - prev).days > 3:
            gaps.append(_gap(ticker, run_start, prev))
            run_start = d
        prev = d
    gaps.append(_gap(ticker, run_start, prev))
    return [g for g in gaps if g.missing_days >= min_days]


def _gap(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> PriceGap:
    return PriceGap(
        ticker=ticker,
        start=start.date().isoformat(),
        end=end.date().isoformat(),
        missing_days=len(pd.date_range(start, end, freq="B")),
    )


def preview_price_fill_forward(
    data_dir: str,
    ticker: str,
    through_date: str | None = None,
    max_run_days: int = 30,
) -> ChangePreview:
    """Carry the last known price forward across missing business days.

    Fills interior gaps and, when ``through_date`` is given, extends the series
    to that date. ``max_run_days`` caps how long a single carried run may be:
    filling months from one stale quote produces a flat line that silently
    understates volatility and drawdown, so the default refuses to do it.

    Raises ``ValueError`` if there is nothing to fill.
    """
    df = _load_prices(data_dir, ticker)
    if df.empty:
        raise ValueError(f"Price history for {ticker!r} is empty — nothing to fill forward.")

    end = pd.to_datetime(through_date) if through_date else df.index.max()
    if end < df.index.max():
        raise ValueError(
            f"through_date {through_date} is before the last stored price "
            f"({df.index.max().date()})."
        )

    full = pd.date_range(df.index.min(), end, freq="B")
    filled = df.reindex(full)
    added_idx = full.difference(df.index)
    if len(added_idx) == 0:
        raise ValueError(f"No missing business days for {ticker!r} — nothing to fill.")

    filled["price"] = filled["price"].ffill()
    filled.index.name = "date"

    # Longest consecutive run of synthesised rows, for the cap + warning.
    runs, run = [], 0
    for d in full:
        if d in added_idx:
            run += 1
        else:
            runs.append(run)
            run = 0
    runs.append(run)
    longest = max(runs) if runs else 0

    if longest > max_run_days:
        raise ValueError(
            f"{ticker}: longest gap is {longest} business days, over the "
            f"max_run_days limit of {max_run_days}. Collect real prices instead, "
            "or raise the limit deliberately if a flat carry is genuinely correct."
        )

    warnings = []
    if longest > LONG_FILL_DAYS:
        warnings.append(
            f"{ticker}: longest carried run is {longest} business days. A flat "
            "stretch that long depresses measured volatility and drawdown."
        )

    sample = list(added_idx[:5])
    changes = [
        RowChange(
            key=f"{ticker} {d.date()}",
            op="insert",
            fields=[FieldChange(field="price", after=round(float(filled.loc[d, "price"]), 6))],
        )
        for d in sample
    ]
    if len(added_idx) > len(sample):
        changes.append(
            RowChange(key=f"... {len(added_idx) - len(sample)} more rows", op="insert")
        )

    def _apply() -> int:
        filled.to_parquet(_price_path(data_dir, ticker))
        return len(added_idx)

    return _stage(
        domain="prices",
        data_dir=data_dir,
        summary=(
            f"Fill forward {len(added_idx)} missing business day(s) for {ticker} "
            f"through {end.date()}"
        ),
        target=ticker,
        changes=changes,
        touches=[os.path.join("prices", f"{ticker}.parquet")],
        apply_fn=_apply,
        warnings=warnings,
    )


def _valuation_sanity(data_dir: str, ticker: str, price: float) -> list[str]:
    """Warn when a manual mark is wildly out of step with the recorded cost basis.

    A hand-entered price is the one number in the system with nothing to check
    it, and it multiplies straight through quantity into every portfolio total,
    weight and risk figure. Bonds are the usual trap: quoted per 100 of face but
    often held here as units at ~1, so entering the quote inflates the holding
    by 100x. Comparing against cost basis catches that without needing to know
    the instrument's conventions.
    """
    positions = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    rows = positions[positions["ticker"] == ticker]
    out = []
    for _, r in rows.iterrows():
        basis = float(r["cost_basis"])
        qty = float(r["quantity"])
        if basis <= 0:
            continue
        ratio = price / basis
        if 0.1 <= ratio <= 10:
            continue
        out.append(
            f"{r['portfolio_name']} / {ticker}: a price of {price:g} against a cost "
            f"basis of {basis:g}/unit values {qty:g} units at "
            f"${qty * price:,.2f} versus ${qty * basis:,.2f} at cost "
            f"({ratio:.0f}x). If this is quoted per 100 of face value, the "
            f"per-unit figure is nearer {basis:g}."
        )
    return out


def preview_price_correction(
    data_dir: str, ticker: str, date: str, price: float
) -> ChangePreview:
    """Correct or insert a single price point (a bad tick, a stock-split gap).

    Works for a ticker with no stored history at all, which is how an
    unpriceable holding — a specific Treasury, a private placement — gets a
    manual mark so it stops dropping out of valuations.
    """
    if price <= 0:
        raise ValueError("price must be positive.")

    try:
        df = _load_prices(data_dir, ticker)
    except ValueError:
        df = pd.DataFrame({"price": pd.Series(dtype="float64")})
        df.index = pd.DatetimeIndex([], name="date")

    ts = pd.to_datetime(date)
    exists = ts in df.index
    before = float(df.loc[ts, "price"]) if exists else None

    if exists and np.isclose(before, price):
        raise ValueError(f"{ticker} on {date} is already {price} — nothing to change.")

    updated = df.copy()
    updated.loc[ts, "price"] = price
    updated = updated.sort_index()
    updated.index.name = "date"

    warnings = []
    if before and (price / before > 2 or price / before < 0.5):
        warnings.append(
            f"{ticker} {date}: price moves {before} -> {price} "
            f"({price / before:.2f}x). If this is a split, correcting one point "
            "leaves the rest of the series on the old basis."
        )
    warnings.extend(_valuation_sanity(data_dir, ticker, price))

    def _apply() -> int:
        updated.to_parquet(_price_path(data_dir, ticker))
        return 1

    return _stage(
        domain="prices",
        data_dir=data_dir,
        summary=f"{'Correct' if exists else 'Insert'} {ticker} price on {date} -> {price}",
        target=ticker,
        changes=[RowChange(
            key=f"{ticker} {ts.date()}",
            op="update" if exists else "insert",
            fields=[FieldChange(field="price", before=before, after=price)],
        )],
        touches=[os.path.join("prices", f"{ticker}.parquet")],
        apply_fn=_apply,
        warnings=warnings,
    )


# ── Fund holdings ────────────────────────────────────────────────────────────


def preview_normalise_fund_weights(
    data_dir: str, fund_ticker: str, as_of_date: str | None = None
) -> ChangePreview:
    """Rescale a holdings snapshot so its weights sum to 1.

    Weights are stored as fractions. Vendor CSVs often arrive in percent, or
    summing slightly off after a partial import; both break the lookthrough
    disaggregation in the Exposure tab.
    """
    db = _get_db(data_dir)
    holdings = db.get_fund_holdings(fund_ticker, as_of_date)
    if holdings is None or holdings.empty:
        raise ValueError(f"No holdings snapshot found for {fund_ticker!r}.")

    total = float(holdings["weight"].sum())
    if total <= 0:
        raise ValueError(f"{fund_ticker}: weights sum to {total} — cannot rescale.")
    if np.isclose(total, 1.0, atol=1e-6):
        raise ValueError(f"{fund_ticker}: weights already sum to 1.0 — nothing to do.")

    resolved_date = as_of_date or str(holdings["as_of_date"].iloc[0])
    scaled = holdings.copy()
    scaled["weight"] = scaled["weight"] / total

    warnings = []
    if np.isclose(total, 100.0, rtol=0.05):
        warnings.append(
            f"{fund_ticker}: weights sum to {total:.2f}, so they were almost "
            "certainly imported as percentages rather than fractions."
        )

    sample = scaled.head(5)
    changes = [
        RowChange(
            key=f"{fund_ticker} / {r['holding_ticker']}",
            op="update",
            fields=[FieldChange(
                field="weight",
                before=round(float(holdings.iloc[i]["weight"]), 6),
                after=round(float(r["weight"]), 6),
            )],
        )
        for i, (_, r) in enumerate(sample.iterrows())
    ]
    if len(scaled) > len(sample):
        changes.append(RowChange(key=f"... {len(scaled) - len(sample)} more holdings", op="update"))

    def _apply() -> int:
        db.save_fund_holdings(fund_ticker, resolved_date, scaled)
        return len(scaled)

    return _stage(
        domain="fund_holdings",
        data_dir=data_dir,
        summary=(
            f"Normalise {len(scaled)} {fund_ticker} holding weights "
            f"({total:.4f} -> 1.0) for {resolved_date}"
        ),
        target=f"{fund_ticker} @ {resolved_date}",
        changes=changes,
        touches=["fund_holdings.parquet"],
        apply_fn=_apply,
        warnings=warnings,
    )


# ── Integrity scan ───────────────────────────────────────────────────────────


def scan_data_issues(data_dir: str, portfolio_name: str | None = None) -> ScanReport:
    """Find data problems across positions, assets, prices and fund holdings.

    Read-only — it stages nothing. This is the agent's entry point: diagnose
    first, then propose specific previews for whatever the user wants fixed.
    """
    db = _get_db(data_dir)
    issues: list[Issue] = []

    positions = pd.read_parquet(os.path.join(data_dir, "positions.parquet"))
    if portfolio_name:
        positions = positions[positions["portfolio_name"] == portfolio_name]
    assets = db.get_all_assets()
    known_tickers = set(assets["ticker"])
    portfolios = set(db.list_portfolios())
    trades = _load_trades(data_dir)

    # Positions
    for _, r in positions.iterrows():
        key = f"{r['portfolio_name']} / {r['ticker']}"
        qty, cb = float(r["quantity"]), float(r["cost_basis"])

        if qty <= 0:
            issues.append(Issue(
                severity="error", domain="positions", key=key,
                detail=f"quantity is {qty} — a held position should be positive.",
                suggested_fix="preview_ledger_replay or preview_trade_correction",
            ))
        if cb <= 0 or pd.isna(cb):
            issues.append(Issue(
                severity="error", domain="positions", key=key,
                detail=f"cost_basis is {cb} — missing or non-positive.",
                suggested_fix="preview_opening_balance",
            ))
        if r["ticker"] not in known_tickers:
            issues.append(Issue(
                severity="error", domain="positions", key=key,
                detail=f"{r['ticker']} is not in the security master.",
                suggested_fix="preview_asset_fix (after adding the asset)",
            ))
        if r["portfolio_name"] not in portfolios:
            issues.append(Issue(
                severity="error", domain="positions", key=key,
                detail=(
                    f"portfolio {r['portfolio_name']!r} holds positions but is absent "
                    "from portfolios.parquet, so it will not appear in listings."
                ),
                suggested_fix="Database.save_portfolio to resync",
            ))

    # Positions vs ledger drift
    for pname in sorted(positions["portfolio_name"].unique()):
        if not _ledger_tickers(trades, str(pname)):
            continue  # nothing to compare against
        _, _, drift = _replayed_positions(data_dir, trades, str(pname))
        if not drift:
            continue
        risks = _replay_risks(drift)
        if risks:
            # Do not point at preview_ledger_replay here: the positions are
            # very likely right and the ledger merely incomplete, so replaying
            # would destroy real holdings.
            issues.append(Issue(
                severity="warning", domain="positions", key=str(pname),
                detail=(
                    f"trade ledger looks INCOMPLETE — a replay would change what "
                    f"you hold in {len(risks)} case(s): {risks[0]}"
                    + (f" (+{len(risks) - 1} more)" if len(risks) > 1 else "")
                    + ". The positions are probably correct and the ledger is "
                    "missing or duplicating history. Do NOT replay."
                ),
                suggested_fix="reconcile the ledger: insert_trade / seed_opening_balance",
            ))
        else:
            issues.append(Issue(
                severity="warning", domain="positions", key=str(pname),
                detail=(
                    f"{len(drift)} position(s) disagree with a replay of the "
                    "trade ledger."
                ),
                suggested_fix="preview_ledger_replay",
            ))

    # Security master
    for _, r in assets.iterrows():
        missing = [c for c in ("name", "sector", "currency") if not str(r.get(c, "")).strip()]
        if missing:
            issues.append(Issue(
                severity="warning", domain="assets", key=str(r["ticker"]),
                detail=f"missing {', '.join(missing)}.",
                suggested_fix="preview_asset_fix",
            ))
        try:
            AssetType(r["asset_type"])
        except (ValueError, KeyError):
            issues.append(Issue(
                severity="error", domain="assets", key=str(r["ticker"]),
                detail=f"asset_type {r.get('asset_type')!r} is not a valid AssetType.",
                suggested_fix="preview_asset_fix",
            ))

    # Prices — only for tickers actually held
    held = sorted(set(positions["ticker"]))
    cash_like = set(
        assets.loc[assets["asset_type"].isin(["Cash", "CD"]), "ticker"]
    )
    for ticker in held:
        if ticker in cash_like:
            continue  # held at par by definition; no price file expected
        if not os.path.exists(_price_path(data_dir, ticker)):
            issues.append(Issue(
                severity="warning", domain="prices", key=ticker,
                detail="no stored price history.",
                suggested_fix="invest-monitor collect",
            ))
            continue
        for gap in find_price_gaps(data_dir, ticker, min_days=2):
            issues.append(Issue(
                severity="warning", domain="prices", key=ticker,
                detail=f"{gap.missing_days} missing business day(s) {gap.start} -> {gap.end}.",
                suggested_fix="preview_price_fill_forward",
            ))

    # Fund holdings
    try:
        funds = db.list_funds_with_holdings()
    except Exception:
        funds = []
    for fund in funds:
        h = db.get_fund_holdings(fund)
        if h is None or h.empty:
            continue
        total = float(h["weight"].sum())
        if not np.isclose(total, 1.0, atol=1e-3):
            issues.append(Issue(
                severity="warning", domain="fund_holdings", key=str(fund),
                detail=f"weights sum to {total:.4f}, not 1.0.",
                suggested_fix="preview_normalise_fund_weights",
            ))

    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (order[i.severity], i.domain, i.key))

    counts: dict[str, int] = {}
    for i in issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1

    return ScanReport(data_dir=data_dir, issues=issues, counts=counts)


__all__ = [
    "scan_data_issues",
    "find_price_gaps",
    "preview_trade_correction",
    "preview_trade_insert",
    "preview_trade_delete",
    "preview_opening_balance",
    "preview_ledger_replay",
    "preview_asset_fix",
    "preview_price_fill_forward",
    "preview_price_correction",
    "preview_normalise_fund_weights",
    "apply_change",
    "discard_change",
    "list_staged",
    "reset_staged",
    "read_audit_log",
]

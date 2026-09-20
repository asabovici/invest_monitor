"""Look-through exposure — what the portfolio actually holds, not what it lists.

A holding of VTI is not "one ETF"; it is ~36% technology, ~12% financials and
so on. This module pushes every position down to its underlying weights using
the stored fund profiles, so a portfolio of index funds reports real sector
concentration instead of a single opaque "ETF" bucket.

Three rules the numbers depend on:

1. **Sectors are equity-only.** yfinance reports `sector_weightings` for the
   equity sleeve alone, so a bond or commodity fund has zero sector rows —
   correctly, not missingly. Sector weights are therefore taken as a share of
   the *equity* base, never of the whole portfolio; dividing by total value
   would understate every sector by the size of the fixed-income book.

2. **Weights get renormalised.** Leveraged and inverse funds legitimately
   report more than 100% (SH sums to ~2.0 across long cash and short
   exposure). Rescaling to 1 keeps a single holding from silently
   double-counting itself into the totals; the affected tickers are reported.

3. **Inverse funds hold negative equity.** SH reports ``stockPosition: -1.0``,
   so it subtracts from the Equity asset class. That short cannot be spread
   across sectors without short-side sector weights, so the sector base is
   long equity only and the difference is reported as ``short_equity``.

4. **Unclassifiable value is surfaced, not hidden.** A fund with no stored
   profile lands in `unclassified` and is named in `unprofiled_funds`, so a
   client can say "this explains 94% of the book" rather than implying it
   explains all of it.
"""

from __future__ import annotations

import os
from collections import defaultdict

import pandas as pd

from src.services._db import _get_db
from src.services.schemas.exposure import Breakdown, Contributor, ExposureReport, Slice

# yfinance's asset-class keys → the labels a person reads.
_CLASS_LABELS = {
    "stockPosition": "Equity",
    "bondPosition": "Bonds",
    "cashPosition": "Cash",
    "otherPosition": "Other",
    "preferredPosition": "Preferred",
    "convertiblePosition": "Convertibles",
}

# Fund profiles use snake_case; the security master uses yfinance's display
# form. Both must land on the same label or a stock and a fund holding the
# same sector would show up as two buckets.
_SECTOR_SPECIAL = {"realestate": "Real Estate"}

_CASH_TYPES = {"Cash", "CD"}
_FUND_TYPES = {"ETF", "Fund"}


def _sector_label(key: str) -> str:
    if key in _SECTOR_SPECIAL:
        return _SECTOR_SPECIAL[key]
    return key.replace("_", " ").title()


def _load_profiles(data_dir: str) -> tuple[dict[str, dict[str, dict[str, float]]], str]:
    """Latest stored profile per fund: {ticker: {category: {key: weight}}}."""
    path = os.path.join(data_dir, "fund_profiles.parquet")
    if not os.path.exists(path):
        return {}, ""
    try:
        df = pd.read_parquet(path)
    except (OSError, ValueError):
        return {}, ""
    if df.empty:
        return {}, ""

    as_of = str(df["as_of_date"].max())
    latest = df[df["as_of_date"] == as_of]

    out: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for r in latest.itertuples():
        out[str(r.fund_ticker)][str(r.category)][str(r.key)] = float(r.weight)
    return {k: dict(v) for k, v in out.items()}, as_of


def _normalised(weights: dict[str, float]) -> tuple[dict[str, float], bool]:
    """Rescale weights to sum to 1. Returns the weights and whether it changed."""
    total = sum(weights.values())
    if total <= 0:
        return {}, False
    if abs(total - 1.0) <= 0.01:
        return weights, False
    return {k: v / total for k, v in weights.items()}, True


def _breakdown(
    buckets: dict[str, float],
    contributors: dict[str, dict[str, float]],
    base: float,
    unclassified: float,
    names: dict[str, str],
    top_n: int = 4,
) -> Breakdown:
    covered = base - unclassified
    slices = [
        Slice(label=k, value=round(v, 2), weight=(v / base) if base else 0.0)
        for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])
        if v > 0.005
    ]
    top = {
        label: [
            Contributor(ticker=t, name=names.get(t, t), value=round(v, 2))
            for t, v in sorted(by_ticker.items(), key=lambda kv: -kv[1])[:top_n]
            if v > 0.005
        ]
        for label, by_ticker in contributors.items()
    }
    return Breakdown(
        slices=slices,
        base=round(base, 2),
        covered=round(covered, 2),
        unclassified=round(unclassified, 2),
        top_contributors={k: v for k, v in top.items() if v},
    )


def get_exposure(data_dir: str) -> ExposureReport:
    """Look-through exposure by asset class and by equity sector.

    Raises ``ValueError`` when the portfolio has no priced holdings.
    """
    from src.services.dashboard import get_snapshot

    snap = get_snapshot(data_dir)
    if not snap.holdings:
        raise ValueError("No priced holdings — nothing to break down.")

    db = _get_db(data_dir)
    assets = db.get_all_assets().set_index("ticker")
    sectors = assets["sector"] if "sector" in assets.columns else pd.Series(dtype=str)

    profiles, as_of = _load_profiles(data_dir)

    cls_buckets: dict[str, float] = defaultdict(float)
    cls_contrib: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sec_buckets: dict[str, float] = defaultdict(float)
    sec_contrib: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    total = 0.0
    equity_base = 0.0
    short_equity = 0.0
    equity_classified = 0.0
    cls_unclassified = 0.0
    unprofiled: list[str] = []
    renormalised: set[str] = set()
    names = {h.ticker: h.name for h in snap.holdings}

    for h in snap.holdings:
        mv = h.market_value
        total += mv

        # ── Direct holdings: no lookthrough needed ────────────────────────
        if h.asset_type in _CASH_TYPES:
            cls_buckets["Cash"] += mv
            cls_contrib["Cash"][h.ticker] += mv
            continue
        if h.asset_type == "Bond":
            cls_buckets["Bonds"] += mv
            cls_contrib["Bonds"][h.ticker] += mv
            continue
        if h.asset_type not in _FUND_TYPES:
            cls_buckets["Equity"] += mv
            cls_contrib["Equity"][h.ticker] += mv
            equity_base += mv
            label = str(sectors.get(h.ticker, "") or "").strip()
            if label:
                sec_buckets[label] += mv
                sec_contrib[label][h.ticker] += mv
                equity_classified += mv
            continue

        # ── Funds: disaggregate through the stored profile ────────────────
        profile = profiles.get(h.ticker, {})
        classes, changed = _normalised(profile.get("asset_class", {}))
        if changed:
            renormalised.add(h.ticker)
        if not classes:
            unprofiled.append(h.ticker)
            cls_unclassified += mv
            continue

        equity_slice = 0.0
        for key, w in classes.items():
            label = _CLASS_LABELS.get(key, "Other")
            part = mv * w
            cls_buckets[label] += part
            cls_contrib[label][h.ticker] += part
            if label == "Equity":
                equity_slice += part

        if equity_slice <= 0:
            # An inverse fund reports negative stockPosition. It correctly
            # reduces the Equity asset class, but it cannot be spread across
            # sectors without the fund's short-side sector weights, so the
            # sector base stays long-only and the shortfall is reported
            # rather than quietly dropped.
            short_equity += -equity_slice
            continue
        equity_base += equity_slice

        sector_w, sec_changed = _normalised(profile.get("sector", {}))
        if sec_changed:
            renormalised.add(h.ticker)
        if not sector_w:
            continue
        for key, w in sector_w.items():
            label = _sector_label(key)
            part = equity_slice * w
            sec_buckets[label] += part
            sec_contrib[label][h.ticker] += part
        equity_classified += equity_slice

    return ExposureReport(
        market_value=round(total, 2),
        by_asset_class=_breakdown(cls_buckets, cls_contrib, total, cls_unclassified, names),
        by_sector=_breakdown(
            sec_buckets, sec_contrib, equity_base, equity_base - equity_classified, names
        ),
        short_equity=round(short_equity, 2),
        as_of=as_of,
        unprofiled_funds=sorted(set(unprofiled)),
        renormalised_funds=sorted(renormalised),
    )


__all__ = ["get_exposure"]

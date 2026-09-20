"""Portfolio-wide income projection.

The per-portfolio calculation already exists in ``services.reports.
income_projection``, which wraps ``ReportingEngine.compute_portfolio_income``.
This module aggregates it across every account rather than reimplementing the
rate arithmetic, because the unit rules are easy to get subtly wrong:

* **Stock / ETF / Fund** — ``income_rate`` is dollars per share per *payment*,
  so annual income is ``quantity × rate × payment_frequency``.
* **Bond / CD / Cash** — ``income_rate`` is an annual *percent* of value, so
  annual income is ``value × rate / 100``.

Reading the rate in the wrong unit is off by orders of magnitude, and nothing
in the number itself reveals the mistake. Delegating keeps one implementation.

The projected total is a **floor**: a holding with no rate on record
contributes nothing, and there is no way to tell "genuinely pays nothing"
from "nobody filled this in" without going back to the source. Both are
reported so a caller can say which.
"""

from __future__ import annotations

from src.services._db import _get_db
from src.services.schemas.income import IncomeBucket, IncomeHolding, IncomeReport

_NON_PAYING_BY_NATURE = {"Crypto"}


def _bucket(rows: list[IncomeHolding], key) -> list[IncomeBucket]:
    totals: dict[str, list[float]] = {}
    for r in rows:
        k = key(r)
        acc = totals.setdefault(k, [0.0, 0.0])
        acc[0] += r.annual_income
        acc[1] += r.market_value
    out = [
        IncomeBucket(
            label=k,
            annual_income=round(income, 2),
            market_value=round(value, 2),
            yield_pct=round(income / value * 100, 4) if value else 0.0,
        )
        for k, (income, value) in totals.items()
    ]
    return sorted(out, key=lambda b: -b.annual_income)


def get_income(data_dir: str) -> IncomeReport:
    """Projected income across every account.

    Raises:
        ValueError: no priced holdings.
    """
    from src.services.dashboard import get_snapshot
    from src.services.reports import income_projection

    snap = get_snapshot(data_dir)
    if not snap.holdings:
        raise ValueError("No priced holdings — nothing to project.")

    db = _get_db(data_dir)
    assets = db.get_all_assets().set_index("ticker")
    names = {h.ticker: h.name for h in snap.holdings}
    latest = {h.ticker: h.price for h in snap.holdings}

    # The per-portfolio service owns the rate arithmetic; key its rows by
    # ticker so they can be matched back to the priced holdings.
    projected: dict[tuple[str, str], float] = {}
    for account in db.list_portfolios():
        try:
            report = income_projection(data_dir, account, latest_prices=latest)
        except ValueError:
            continue
        for row in report.rows:
            projected[(account, row.ticker)] = row.annual_income

    rows: list[IncomeHolding] = []
    non_income_value = 0.0
    non_income: list[str] = []

    for h in snap.holdings:
        annual = projected.get((h.account, h.ticker), 0.0)
        if annual <= 0:
            non_income_value += h.market_value
            if h.asset_type not in _NON_PAYING_BY_NATURE:
                non_income.append(h.ticker)
            continue
        try:
            freq = int(assets.loc[h.ticker, "payment_frequency"])
        except (KeyError, TypeError, ValueError):
            freq = 1
        rows.append(IncomeHolding(
            ticker=h.ticker,
            name=names.get(h.ticker, h.ticker),
            account=h.account,
            asset_type=h.asset_type,
            market_value=round(h.market_value, 2),
            annual_income=round(annual, 2),
            monthly_income=round(annual / 12, 2),
            yield_pct=round(annual / h.market_value * 100, 4) if h.market_value else 0.0,
            payment_frequency=freq,
        ))

    rows.sort(key=lambda r: -r.annual_income)
    annual_total = sum(r.annual_income for r in rows)

    return IncomeReport(
        market_value=snap.market_value,
        annual_income=round(annual_total, 2),
        monthly_income=round(annual_total / 12, 2),
        portfolio_yield_pct=(
            round(annual_total / snap.market_value * 100, 4) if snap.market_value else 0.0
        ),
        by_asset_type=_bucket(rows, lambda r: r.asset_type),
        by_account=_bucket(rows, lambda r: r.account),
        holdings=rows,
        non_income_value=round(non_income_value, 2),
        non_income_tickers=sorted(set(non_income)),
    )


__all__ = ["get_income"]

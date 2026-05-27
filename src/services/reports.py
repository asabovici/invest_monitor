"""Reports service: risk, exposure, income, correlation, attribution.

Slice 4 of the API refactor — see API_REFACTOR_PLAN.md §5. Reads only;
the refresh side (writing daily metrics to parquet) belongs to slice 11
alongside the production runner.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

import numpy as np
import pandas as pd

from src.api.schemas.report import (
    AttributionContributor,
    AttributionReport,
    CorrelationReport,
    ExposureReport,
    ExposureRow,
    IncomeProjectionReport,
    IncomeProjectionRow,
    RiskMetricsReport,
)
from src.database import Database
from src.reporting import ReportingEngine


# ── Internal helpers ─────────────────────────────────────────────────────────


def _require_portfolio(db: Database, name: str):
    """Load the domain Portfolio or raise ValueError. Surfaced as 404 by routers."""
    return db.get_portfolio(name)


def _normalise_iso(d) -> date:
    """Coerce a Timestamp/datetime/date-ish into a plain ``date``."""
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    return pd.Timestamp(d).date()


def _matrix_to_dict(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """``df`` is square with matching index/columns. Convert to nested dict."""
    out: dict[str, dict[str, float]] = {}
    for row_ticker in df.index:
        row: dict[str, float] = {}
        for col_ticker in df.columns:
            val = df.at[row_ticker, col_ticker]
            row[str(col_ticker)] = 0.0 if pd.isna(val) else float(val)
        out[str(row_ticker)] = row
    return out


# ── Reports ──────────────────────────────────────────────────────────────────


def risk_metrics(data_dir: str, portfolio_name: str) -> RiskMetricsReport:
    """Annualised vol, daily 95% VaR (hist + MC), covariance + correlation matrices.

    Raises:
        ValueError: portfolio not found.
    """
    db = Database(data_dir)
    portfolio = _require_portfolio(db, portfolio_name)
    metrics = ReportingEngine(db).get_portfolio_risk_metrics(portfolio)

    cov_df: pd.DataFrame = metrics["Covariance Matrix"]
    # Correlation derived from annualised covariance — same shape, same tickers.
    if cov_df.empty:
        corr_df = cov_df
    else:
        sd = np.sqrt(np.diag(cov_df.values))
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = cov_df.values / np.outer(sd, sd)
        corr_df = pd.DataFrame(corr, index=cov_df.index, columns=cov_df.columns).fillna(0.0)

    return RiskMetricsReport(
        portfolio_name=portfolio.name,
        annualised_volatility=float(metrics["Volatility"]),
        historical_var_95=float(metrics["Historical VaR (95%)"]),
        monte_carlo_var_95=float(metrics["Monte Carlo VaR (95%)"]),
        tickers=list(cov_df.columns),
        covariance_matrix=_matrix_to_dict(cov_df),
        correlation_matrix=_matrix_to_dict(corr_df),
    )


def exposure(data_dir: str, portfolio_name: str) -> ExposureReport:
    """Cost-basis exposure grouped by ``(asset_type, sector)``.

    This mirrors the existing ``ReportingEngine.get_portfolio_exposure``
    cost-basis-weighted view. Latest-price-weighted exposure is a future
    enhancement and would belong to a separate endpoint.

    Raises:
        ValueError: portfolio not found.
    """
    db = Database(data_dir)
    portfolio = _require_portfolio(db, portfolio_name)

    rows_raw: list[dict] = []
    total = 0.0
    for pos in portfolio.positions:
        value = pos.quantity * pos.cost_basis
        total += value
        if pos.asset.is_composite():
            for c in pos.asset.constituents:
                rows_raw.append({
                    "asset_type": "Constituent",
                    "sector": "Look-through",
                    "value": c.weight * value,
                })
        else:
            rows_raw.append({
                "asset_type": pos.asset.asset_type.value,
                "sector": pos.asset.sector,
                "value": value,
            })

    bucketed: dict[tuple[str, str | None], float] = {}
    for r in rows_raw:
        key = (r["asset_type"], r["sector"])
        bucketed[key] = bucketed.get(key, 0.0) + r["value"]

    rows = [
        ExposureRow(
            asset_type=at,
            sector=sec,
            market_value=v,
            weight_pct=(v / total * 100.0) if total else 0.0,
        )
        for (at, sec), v in sorted(bucketed.items(), key=lambda kv: -kv[1])
    ]
    return ExposureReport(
        portfolio_name=portfolio.name,
        total_value=total,
        rows=rows,
    )


def income_projection(
    data_dir: str,
    portfolio_name: str,
    latest_prices: dict[str, float] | None = None,
) -> IncomeProjectionReport:
    """Annual + monthly income projection per position, plus portfolio totals.

    Passing ``latest_prices`` (e.g. from the ``prices`` service) anchors
    rate-as-percent assets to current market value rather than cost basis.
    Without it the calculation falls back to ``qty × cost_basis_per_share``.

    Raises:
        ValueError: portfolio not found.
    """
    db = Database(data_dir)
    portfolio = _require_portfolio(db, portfolio_name)
    df = ReportingEngine(db).compute_portfolio_income(portfolio, latest_prices=latest_prices)

    rows = [
        IncomeProjectionRow(
            ticker=r["Ticker"],
            asset_type=r["Type"],
            base_value=float(r["Base Value"]),
            income_rate=float(r["Income Rate"]),
            income_rate_unit=str(r["Income Rate Unit"]),
            annual_income=float(r["Annual Income"]),
            monthly_income=float(r["Monthly Income"]),
            payment_frequency=int(r["Payment Frequency"]),
            yield_on_base_pct=float(r["Yield on Base (%)"]),
        )
        for _, r in df.iterrows()
    ]
    total_annual = sum(r.annual_income for r in rows)
    return IncomeProjectionReport(
        portfolio_name=portfolio.name,
        rows=rows,
        total_annual_income=total_annual,
        total_monthly_income=total_annual / 12.0,
    )


def correlation_matrix(data_dir: str, portfolio_name: str) -> CorrelationReport:
    """Pairwise correlation of daily returns across the portfolio's tickers.

    Same numbers as ``risk_metrics``'s correlation matrix but standalone
    for clients that don't want the rest of the risk payload.

    Raises:
        ValueError: portfolio not found.
    """
    db = Database(data_dir)
    portfolio = _require_portfolio(db, portfolio_name)
    tickers = [pos.asset.ticker for pos in portfolio.positions]
    if not tickers:
        return CorrelationReport(portfolio_name=portfolio.name, tickers=[], matrix={})
    returns = ReportingEngine(db).calculate_returns(tickers)
    if returns.empty:
        return CorrelationReport(portfolio_name=portfolio.name, tickers=tickers, matrix={})
    corr_df = returns.corr().fillna(0.0)
    return CorrelationReport(
        portfolio_name=portfolio.name,
        tickers=list(corr_df.columns),
        matrix=_matrix_to_dict(corr_df),
    )


def attribution(
    data_dir: str,
    portfolio_name: str,
    start: date | str | None = None,
    end: date | str | None = None,
    top_n: int = 5,
) -> AttributionReport:
    """Performance attribution over a date range.

    Reads pre-computed ``daily_portfolio_metrics`` and
    ``daily_attribution``. Empty parquet (no metrics refresh yet) returns
    a zero-filled report rather than failing.

    Raises:
        ValueError: portfolio not found in the portfolios table (we
            check this even if no daily metrics exist yet).
    """
    db = Database(data_dir)
    _require_portfolio(db, portfolio_name)

    start_str = start.isoformat() if isinstance(start, date) else (start or None)
    portfolio_df = db.get_daily_portfolio_metrics(
        portfolio_name=portfolio_name, start_date=start_str,
    )
    attribution_df = db.get_daily_attribution(
        portfolio_name=portfolio_name, start_date=start_str,
    )

    if end is not None:
        end_str = end.isoformat() if isinstance(end, date) else end
        if not portfolio_df.empty:
            portfolio_df = portfolio_df[pd.to_datetime(portfolio_df["date"]) <= pd.to_datetime(end_str)]
        if not attribution_df.empty:
            attribution_df = attribution_df[pd.to_datetime(attribution_df["date"]) <= pd.to_datetime(end_str)]

    if portfolio_df.empty:
        # No daily metrics — return an empty report rather than 500.
        today = date.today()
        return AttributionReport(
            portfolio_name=portfolio_name,
            start_date=_normalise_iso(start) if start else today,
            end_date=_normalise_iso(end) if end else today,
            cumulative_return=0.0,
            max_drawdown=0.0,
            dates=[],
            daily_returns=[],
            top_contributors=[],
            top_detractors=[],
        )

    portfolio_df = portfolio_df.sort_values("date").reset_index(drop=True)
    dates = [_normalise_iso(d) for d in portfolio_df["date"]]
    daily_returns = [
        None if pd.isna(v) else float(v) for v in portfolio_df["daily_return"].tolist()
    ]

    # Cumulative return: prefer the persisted value at the end of window,
    # falling back to compounding daily_return if missing.
    cum_col = portfolio_df["cum_return"].dropna()
    cumulative_return = float(cum_col.iloc[-1]) if not cum_col.empty else 0.0
    # max_drawdown is persisted as a negative decimal (or 0); take the min.
    max_dd_col = portfolio_df["max_drawdown"].dropna()
    max_drawdown = float(max_dd_col.min()) if not max_dd_col.empty else 0.0

    # Contributors / detractors by total contribution_to_return over the window.
    top_contributors: list[AttributionContributor] = []
    top_detractors: list[AttributionContributor] = []
    if not attribution_df.empty and "contribution_to_return" in attribution_df.columns:
        grouped = (
            attribution_df.groupby("ticker")
            .agg(
                contribution_to_return=("contribution_to_return", "sum"),
                average_weight=("weight", "mean"),
            )
            .reset_index()
            .dropna(subset=["contribution_to_return"])
        )
        ranked = grouped.sort_values("contribution_to_return", ascending=False)
        positives = ranked[ranked["contribution_to_return"] > 0].head(top_n)
        negatives = ranked[ranked["contribution_to_return"] < 0].tail(top_n).iloc[::-1]
        top_contributors = [
            AttributionContributor(
                ticker=r["ticker"],
                contribution_to_return=float(r["contribution_to_return"]),
                average_weight=float(r["average_weight"] or 0.0),
            )
            for _, r in positives.iterrows()
        ]
        top_detractors = [
            AttributionContributor(
                ticker=r["ticker"],
                contribution_to_return=float(r["contribution_to_return"]),
                average_weight=float(r["average_weight"] or 0.0),
            )
            for _, r in negatives.iterrows()
        ]

    return AttributionReport(
        portfolio_name=portfolio_name,
        start_date=dates[0],
        end_date=dates[-1],
        cumulative_return=cumulative_return,
        max_drawdown=max_drawdown,
        dates=dates,
        daily_returns=daily_returns,
        top_contributors=top_contributors,
        top_detractors=top_detractors,
    )


# ── DataFrame helpers for in-process callers (Streamlit, agents) ────────────


_INCOME_COLUMN_MAP = {
    "ticker": "Ticker",
    "asset_type": "Type",
    "base_value": "Base Value",
    "income_rate": "Income Rate",
    "income_rate_unit": "Income Rate Unit",
    "annual_income": "Annual Income",
    "monthly_income": "Monthly Income",
    "payment_frequency": "Payment Frequency",
    "yield_on_base_pct": "Yield on Base (%)",
}


def income_report_to_dataframe(report: IncomeProjectionReport) -> pd.DataFrame:
    """Convert ``IncomeProjectionReport`` to the legacy DataFrame column shape."""
    if not report.rows:
        return pd.DataFrame(columns=list(_INCOME_COLUMN_MAP.values()))
    df = pd.DataFrame([r.model_dump() for r in report.rows])
    return df.rename(columns=_INCOME_COLUMN_MAP)


def covariance_to_dataframe(report: RiskMetricsReport) -> pd.DataFrame:
    """Convert the covariance dict back to a labelled DataFrame."""
    if not report.tickers:
        return pd.DataFrame()
    return pd.DataFrame(report.covariance_matrix, index=report.tickers, columns=report.tickers)


def correlation_to_dataframe(report: CorrelationReport) -> pd.DataFrame:
    """Convert the correlation dict back to a labelled DataFrame."""
    if not report.tickers:
        return pd.DataFrame()
    return pd.DataFrame(report.matrix, index=report.tickers, columns=report.tickers)


__all__ = [
    "risk_metrics",
    "exposure",
    "income_projection",
    "correlation_matrix",
    "attribution",
    "income_report_to_dataframe",
    "covariance_to_dataframe",
    "correlation_to_dataframe",
]

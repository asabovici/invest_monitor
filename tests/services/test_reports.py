"""Tests for src/services/reports.py against the demo dataset."""

import pytest

from src.services.reports import (
    attribution,
    correlation_matrix,
    correlation_to_dataframe,
    covariance_to_dataframe,
    exposure,
    income_projection,
    income_report_to_dataframe,
    risk_metrics,
)

DEMO = "data_demo"
PORTFOLIO = "Demo Retirement"


# ── Risk ─────────────────────────────────────────────────────────────────────


def test_risk_metrics_has_realistic_values() -> None:
    report = risk_metrics(DEMO, PORTFOLIO)
    assert report.portfolio_name == PORTFOLIO
    assert report.tickers
    assert report.annualised_volatility > 0
    # Daily VaR should be a small negative number (a percentile of returns).
    assert -1.0 < report.historical_var_95 < 0.0
    # Covariance matrix is square and named.
    n = len(report.tickers)
    assert len(report.covariance_matrix) == n
    for row in report.covariance_matrix.values():
        assert len(row) == n


def test_risk_metrics_correlation_diagonal_is_one() -> None:
    report = risk_metrics(DEMO, PORTFOLIO)
    for t in report.tickers:
        assert report.correlation_matrix[t][t] == pytest.approx(1.0, rel=1e-6)


def test_risk_metrics_missing_portfolio_raises() -> None:
    with pytest.raises(ValueError):
        risk_metrics(DEMO, "does-not-exist")


def test_covariance_to_dataframe_round_trip() -> None:
    report = risk_metrics(DEMO, PORTFOLIO)
    df = covariance_to_dataframe(report)
    assert list(df.columns) == report.tickers
    assert list(df.index) == report.tickers


# ── Exposure ─────────────────────────────────────────────────────────────────


def test_exposure_totals_match_sum_of_rows() -> None:
    report = exposure(DEMO, PORTFOLIO)
    assert report.total_value > 0
    row_total = sum(r.market_value for r in report.rows)
    assert row_total == pytest.approx(report.total_value)
    weight_total = sum(r.weight_pct for r in report.rows)
    assert weight_total == pytest.approx(100.0, abs=0.01)


# ── Income ───────────────────────────────────────────────────────────────────


def test_income_projection_totals_consistent() -> None:
    report = income_projection(DEMO, PORTFOLIO)
    annual = sum(r.annual_income for r in report.rows)
    assert report.total_annual_income == pytest.approx(annual)
    assert report.total_monthly_income == pytest.approx(annual / 12.0)


def test_income_report_to_dataframe_has_legacy_columns() -> None:
    report = income_projection(DEMO, PORTFOLIO)
    df = income_report_to_dataframe(report)
    for col in ("Ticker", "Type", "Base Value", "Annual Income"):
        assert col in df.columns


# ── Correlation ──────────────────────────────────────────────────────────────


def test_correlation_matrix_is_symmetric() -> None:
    report = correlation_matrix(DEMO, PORTFOLIO)
    for a in report.tickers:
        for b in report.tickers:
            assert report.matrix[a][b] == pytest.approx(report.matrix[b][a])


def test_correlation_to_dataframe_round_trip() -> None:
    report = correlation_matrix(DEMO, PORTFOLIO)
    df = correlation_to_dataframe(report)
    assert list(df.columns) == report.tickers


# ── Attribution ──────────────────────────────────────────────────────────────


def test_attribution_returns_aligned_dates_and_returns() -> None:
    report = attribution(DEMO, PORTFOLIO)
    assert report.dates
    assert len(report.daily_returns) == len(report.dates)
    assert report.start_date == report.dates[0]
    assert report.end_date == report.dates[-1]


def test_attribution_top_contributors_have_positive_sums() -> None:
    report = attribution(DEMO, PORTFOLIO, top_n=3)
    for c in report.top_contributors:
        assert c.contribution_to_return > 0
    for d in report.top_detractors:
        assert d.contribution_to_return < 0


def test_attribution_unknown_portfolio_raises() -> None:
    with pytest.raises(ValueError):
        attribution(DEMO, "does-not-exist")

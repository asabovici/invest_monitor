"""Tests for src/services/benchmarks.py against the demo dataset."""

import pytest

from src.services.benchmarks import (
    benchmark_returns,
    benchmark_stats,
    compare_to_benchmark,
    list_benchmarks,
)

DEMO = "data_demo"


def test_list_benchmarks_returns_catalogue() -> None:
    items = list_benchmarks()
    names = {b.name for b in items}
    assert "60/40 Classic" in names
    for b in items:
        assert b.weights
        # Weights should sum close to 1.0 by construction.
        assert sum(b.weights.values()) == pytest.approx(1.0, abs=0.01)


def test_benchmark_returns_unknown_raises() -> None:
    with pytest.raises(ValueError):
        benchmark_returns(DEMO, "Not A Real Benchmark")


def test_benchmark_stats_unknown_raises() -> None:
    with pytest.raises(ValueError):
        benchmark_stats(DEMO, "Not A Real Benchmark")


def test_compare_to_benchmark_unknown_portfolio_raises() -> None:
    with pytest.raises(ValueError):
        compare_to_benchmark(DEMO, "no-such-portfolio", "60/40 Classic")


def test_compare_to_benchmark_aligns_dates() -> None:
    """Demo data lacks the public ETF proxies, so the benchmark side will be
    empty — but the portfolio side should still produce a non-empty series and
    the date list should match the longer of the two."""
    comp = compare_to_benchmark(DEMO, "Demo Retirement", "60/40 Classic")
    assert comp.portfolio_name == "Demo Retirement"
    assert comp.benchmark_name == "60/40 Classic"
    assert len(comp.portfolio_cumulative_returns) == len(comp.dates)
    assert len(comp.benchmark_cumulative_returns) == len(comp.dates)
    # Portfolio stats should be populated from the persisted daily metrics.
    assert comp.portfolio_stats.period_return is not None

"""Tests for the performance (rebased price history) service.

A chart silently depends on alignment: every series must be the same length
as the shared date axis, and every series must start at zero or the lines
are not comparable. Those are the invariants pinned here.
"""

import shutil

import pytest

from src.services import performance
from src.services._db import reset_db_cache


@pytest.fixture(autouse=True)
def _clean():
    reset_db_cache()
    yield
    reset_db_cache()


@pytest.fixture
def data_dir(tmp_path):
    dest = tmp_path / "data"
    shutil.copytree("data_demo", dest)
    return str(dest)


def test_series_are_aligned_to_the_shared_dates(data_dir):
    """A chart draws every series against one x-axis; ragged lengths corrupt it."""
    rep = performance.get_performance(data_dir)
    assert len(rep.dates) > 2
    for s in rep.series:
        assert len(s.cumulative_return) == len(rep.dates), f"{s.ticker} is not aligned"
    assert len(rep.portfolio_cumulative_return) == len(rep.dates)


def test_each_series_starts_at_zero(data_dir):
    """Rebasing means the first real sample is 0% by construction."""
    rep = performance.get_performance(data_dir)
    for s in rep.series:
        first = next((v for v in s.cumulative_return if v is not None), None)
        assert first == pytest.approx(0.0, abs=1e-9), f"{s.ticker} is not rebased"


def test_total_return_matches_the_last_point(data_dir):
    rep = performance.get_performance(data_dir)
    for s in rep.series:
        last = next((v for v in reversed(s.cumulative_return) if v is not None), None)
        assert s.total_return == pytest.approx(last, abs=1e-9)


def test_series_sorted_by_market_value(data_dir):
    rep = performance.get_performance(data_dir)
    values = [s.market_value for s in rep.series]
    assert values == sorted(values, reverse=True)


def test_scoping_narrows_the_series(data_dir):
    whole = performance.get_performance(data_dir)
    scoped = performance.get_performance(data_dir, portfolio="Demo Brokerage")
    assert len(scoped.series) < len(whole.series)


def test_unknown_portfolio_is_not_found(data_dir):
    with pytest.raises(ValueError, match="not found"):
        performance.get_performance(data_dir, portfolio="No Such Account")


def test_start_trims_the_window(data_dir):
    full = performance.get_performance(data_dir)
    trimmed = performance.get_performance(data_dir, start="2025-01-01")
    assert len(trimmed.dates) < len(full.dates)
    assert trimmed.dates[0] >= "2025-01-01"

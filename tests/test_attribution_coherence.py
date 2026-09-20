"""The stored daily-metrics series must stay a single coherent series.

``cum_return``, ``drawdown`` and ``max_drawdown`` are path-dependent: each
is a running figure compounded from the start of the window it was computed
over. Writing them per-date lets two refresh runs leave rows compounded
from different baselines in the same series, which is not a series at all.

This was a live bug. An incremental refresh recomputed only the trailing
30 days, restarting the compound at zero, and upserted those rows over the
existing history. SCHAB then reported -1.18% for a portfolio that had
actually returned +46.77%.
"""

import shutil

import pandas as pd
import pytest

from src.attribution import AttributionEngine
from src.database import Database

PORTFOLIO = "Demo Brokerage"


@pytest.fixture
def data_dir(tmp_path):
    dest = tmp_path / "data"
    shutil.copytree("data_demo", dest)
    return str(dest)


def _stored(data_dir: str, name: str = PORTFOLIO) -> pd.DataFrame:
    df = Database(data_dir=data_dir).get_daily_portfolio_metrics(name)
    return df.sort_values("date").reset_index(drop=True)


def test_incremental_refresh_keeps_the_headline_return_correct(data_dir):
    """The number the Attribution screen shows must survive a second refresh."""
    eng = AttributionEngine(Database(data_dir=data_dir))
    eng.refresh_all(full=True)
    expected = _stored(data_dir)["cum_return"].dropna().iloc[-1]

    eng.refresh_all()  # incremental — the default the production job uses

    after = _stored(data_dir)["cum_return"].dropna().iloc[-1]
    assert after == pytest.approx(expected, abs=1e-9), (
        "an incremental refresh changed the total return; the cumulative "
        "series was rebased partway through"
    )


def test_cumulative_series_has_a_single_baseline(data_dir):
    """Every row's cum_return must be the compound of daily_return to date.

    Checked row by row rather than only at the end: a mid-series rebase can
    cancel out by the last row and still make every intermediate point — and
    the whole chart — wrong.
    """
    eng = AttributionEngine(Database(data_dir=data_dir))
    eng.refresh_all(full=True)
    eng.refresh_all()

    df = _stored(data_dir)
    expected = (1.0 + df["daily_return"].fillna(0.0)).cumprod() - 1.0
    actual = df["cum_return"].fillna(0.0)

    drift = (actual - expected).abs()
    worst = int(drift.idxmax())
    assert drift.max() < 1e-6, (
        f"cum_return diverges from compounded daily_return by "
        f"{drift.max():.4%} at row {worst} ({df['date'].iloc[worst]}): "
        f"stored {actual.iloc[worst]:+.4%} vs compounded {expected.iloc[worst]:+.4%}"
    )


def test_refresh_does_not_shrink_the_stored_history(data_dir):
    """A refresh must not drop dates it did not recompute."""
    eng = AttributionEngine(Database(data_dir=data_dir))
    eng.refresh_all(full=True)
    before = len(_stored(data_dir))

    eng.refresh_all()

    assert len(_stored(data_dir)) >= before


def test_refresh_is_idempotent(data_dir):
    """Running the same refresh twice must not change the stored numbers."""
    eng = AttributionEngine(Database(data_dir=data_dir))
    eng.refresh_all(full=True)
    first = _stored(data_dir)

    eng.refresh_all(full=True)
    second = _stored(data_dir)

    assert len(first) == len(second)
    pd.testing.assert_series_equal(
        first["cum_return"], second["cum_return"], check_exact=False, atol=1e-9
    )

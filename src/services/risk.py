"""Portfolio risk and Monte Carlo projection.

This lifts the Monte Carlo engine out of ``src/agent/wealth_skills.py`` into
the service layer — the migration ``src/services/CLAUDE.md`` lists as deferred
— so the API, CLI and agents all share one implementation.

Three deliberate departures from the version in the agent skill:

1. **Weights are by market value, not cost basis.** The skill weighted the
   portfolio by ``quantity × cost_basis``, which measures what you paid rather
   than what you hold; a position that has tripled was under-weighted in its
   own risk estimate.

2. **Bands are recorded over time, not just at the horizon.** The skill
   returned final percentiles only, which cannot draw a fan chart.

3. **Paths are not materialised.** Simulating 5,000 paths over 20 years as a
   full matrix is ~200 MB of float64. Only the current value vector is kept,
   with percentiles sampled at checkpoints, so memory is O(simulations)
   regardless of horizon.

The projection assumes i.i.d. normal daily returns fitted to trailing history.
That understates tail risk — real returns are fat-tailed and serially
correlated — so treat the bands as a spread of plausible outcomes, not a
confidence interval.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.services.schemas.risk import (
    Projection,
    ProjectionBands,
    RiskMetrics,
    RiskReport,
)

_TRADING_DAYS = 252
_DAYS_PER_MONTH = 21
_SEED = 42


_ANOMALY_THRESHOLD = 0.35
_ANOMALY_WINDOW = 5
_ANOMALY_TOLERANCE = 0.20


def _round_trip_anomalies(s: pd.Series) -> pd.DatetimeIndex:
    """Dates whose price move is a spike that reverses — i.e. a bad price.

    A corrupted quote shows a distinctive shape: the price jumps hard and is
    back near where it started within days. A real move of the same size —
    an earnings crash, a meme-stock squeeze — does not round-trip. Keying on
    the reversal rather than the magnitude means genuine tail events stay in
    the sample, which matters because they are exactly what risk is about.

    Returns the dates on the *far* side of each bad move, so both the drop
    and the recovery are excluded.
    """
    returns = s.pct_change()
    suspect = returns.index[returns.abs() > _ANOMALY_THRESHOLD]
    flagged: list[pd.Timestamp] = []

    for d in suspect:
        i = s.index.get_loc(d)
        if i == 0:
            continue
        before = s.iloc[i - 1]
        window = s.iloc[i : i + _ANOMALY_WINDOW + 1]
        if before <= 0 or window.empty:
            continue
        # Did it come back to roughly where it was?
        recovered = ((window / before - 1).abs() < _ANOMALY_TOLERANCE).any()
        if recovered:
            flagged.append(d)
            # The recovery day is equally bogus as a return.
            back = window.index[(window / before - 1).abs() < _ANOMALY_TOLERANCE]
            flagged.extend(back[:1])

    return pd.DatetimeIndex(sorted(set(flagged)))


def _daily_returns(
    data_dir: str, tickers: list[str]
) -> tuple[pd.DataFrame, list[str]]:
    """Aligned daily returns, with round-trip price glitches masked out.

    Also returns a human-readable note per affected ticker so the caller can
    say what was ignored instead of quietly changing the answer.
    """
    frames: dict[str, pd.Series] = {}
    notes: list[str] = []

    for t in tickers:
        path = os.path.join(data_dir, "prices", f"{t}.parquet")
        if not os.path.exists(path):
            continue
        try:
            s = pd.read_parquet(path)["price"].dropna()
        except (KeyError, OSError, ValueError):
            continue
        if len(s) < 30:
            continue

        s.index = pd.to_datetime(s.index)
        s = s.sort_index()

        bad = _round_trip_anomalies(s)
        returns = s.pct_change().dropna()
        if len(bad):
            returns = returns.drop(index=bad, errors="ignore")
            notes.append(
                f"{t}: {len(bad)} suspect price point(s) ignored "
                f"({', '.join(d.date().isoformat() for d in bad[:3])}"
                f"{'…' if len(bad) > 3 else ''})"
            )
        frames[t] = returns

    if not frames:
        return pd.DataFrame(), notes
    return pd.DataFrame(frames).dropna(how="all"), notes


def _portfolio_returns(
    data_dir: str, weights: dict[str, float]
) -> tuple[pd.Series, int, list[str]]:
    """Weighted daily return series for the portfolio, holdings used, and notes."""
    rets, notes = _daily_returns(data_dir, list(weights))
    if rets.empty:
        return pd.Series(dtype=float), 0, notes

    used = [t for t in rets.columns if weights.get(t, 0) > 0]
    if not used:
        return pd.Series(dtype=float), 0, notes

    total = sum(weights[t] for t in used)
    w = np.array([weights[t] / total for t in used])
    aligned = rets[used].fillna(0.0)
    return pd.Series(aligned.values @ w, index=aligned.index), len(used), notes


def _expected_shortfall(values: np.ndarray, percentile: float) -> float:
    """Mean return among the days at or beyond the VaR cut.

    VaR is a threshold and says nothing about how far past it the bad days
    go; expected shortfall averages exactly those days. Falls back to the
    cut itself when the tail is empty, which happens only on very short
    histories where no observation sits at or below the percentile.
    """
    cut = float(np.percentile(values, percentile))
    tail = values[values <= cut]
    return float(tail.mean()) if tail.size else cut


def _metrics(port: pd.Series) -> RiskMetrics:
    values = port.to_numpy()
    curve = (1 + port).cumprod()
    drawdowns = curve / curve.cummax() - 1
    sigma = float(values.std())
    return RiskMetrics(
        annualised_volatility=round(sigma * np.sqrt(_TRADING_DAYS), 6),
        historical_var_95=round(float(np.percentile(values, 5)), 6),
        # Fitted-normal VaR: mean + z(0.05)·σ, the parametric counterpart to
        # the empirical figure above. They diverge when returns are fat-tailed.
        monte_carlo_var_95=round(float(values.mean() - 1.645 * sigma), 6),
        historical_var_99=round(float(np.percentile(values, 1)), 6),
        expected_shortfall_95=round(_expected_shortfall(values, 5), 6),
        expected_shortfall_99=round(_expected_shortfall(values, 1), 6),
        max_drawdown=round(float(drawdowns.min()), 6),
        # Where the portfolio sits against its own peak today, which is a
        # different question from how bad it ever got.
        current_drawdown=round(float(drawdowns.iloc[-1]), 6),
        best_day=round(float(values.max()), 6),
        worst_day=round(float(values.min()), 6),
        observations=int(len(values)),
    )


def simulate_paths(
    start_value: float,
    num_simulations: int,
    total_days: int,
    daily_params: Callable[[int], tuple[float, float]],
    monthly_contribution: float = 0.0,
    shock_for_day: Callable[[int], float] | None = None,
    checkpoint_every: int | None = None,
    percentiles: Sequence[int] = (5, 25, 50, 75, 95),
    seed: int = _SEED,
) -> tuple[np.ndarray, list[int], dict[int, list[float]]]:
    """Run a Monte Carlo of portfolio value and return the final values.

    The single simulation engine for the project — ``services.risk`` and the
    agent's wealth skills both drive it, so the maths lives in one place.

    ``daily_params(day)`` supplies ``(mu, sigma)`` per 0-based trading day,
    which is what lets a caller vary drift and volatility by regime without
    this function knowing anything about scenarios. ``shock_for_day(day)``
    optionally returns a one-off multiplicative shock applied after that
    day's return.

    Per-day order is fixed and load-bearing: draw, apply return, apply any
    shock, then add the monthly contribution. Callers depend on the exact
    RNG draw sequence for reproducibility, so a single ``rng.normal`` call
    of width ``num_simulations`` happens per day, always.

    Only the current value vector is kept — materialising every path costs
    ~200 MB at 5,000 simulations over 20 years — so memory is
    O(simulations) whatever the horizon.

    Returns ``(final_values, checkpoint_days, {percentile: [values…]})``.
    Checkpoints include day 0.
    """
    rng = np.random.default_rng(seed)
    values = np.full(num_simulations, float(start_value))

    checkpoints: list[int] = [0]
    bands: dict[int, list[float]] = {p: [float(start_value)] for p in percentiles}

    for day in range(1, total_days + 1):
        mu, sigma = daily_params(day - 1)
        values *= 1.0 + rng.normal(mu, max(sigma, 1e-12), num_simulations)

        if shock_for_day is not None:
            shock = shock_for_day(day - 1)
            if shock:
                values *= 1.0 + shock

        if monthly_contribution and day % _DAYS_PER_MONTH == 0:
            values += monthly_contribution

        # A normal draw can push a path below zero; a portfolio cannot follow.
        # With realistic daily sigma this never binds — it is a floor, not a
        # correction — so it does not perturb reproducible results.
        np.maximum(values, 0.0, out=values)

        if checkpoint_every and (day % checkpoint_every == 0 or day == total_days):
            checkpoints.append(day)
            for p in bands:
                bands[p].append(round(float(np.percentile(values, p)), 2))

    return values, checkpoints, bands


def _simulate(
    start_value: float,
    mu: float,
    sigma: float,
    years: float,
    monthly_contribution: float,
    num_simulations: int,
    goal_amount: float | None,
) -> tuple[Projection, np.ndarray]:
    total_days = max(1, int(years * _TRADING_DAYS))
    # ~40 checkpoints is enough to draw a smooth fan without a huge payload.
    every = max(1, total_days // 40)

    finals, checkpoint_days, bands = simulate_paths(
        start_value=start_value,
        num_simulations=num_simulations,
        total_days=total_days,
        daily_params=lambda _day: (mu, sigma),
        monthly_contribution=monthly_contribution,
        checkpoint_every=every,
    )

    today = date.today()
    dates = [
        (today + timedelta(days=int(d * 365 / _TRADING_DAYS))).isoformat()
        for d in checkpoint_days
    ]
    prob = float(np.mean(finals >= goal_amount)) if goal_amount else None

    projection = Projection(
        years=years,
        num_simulations=num_simulations,
        monthly_contribution=monthly_contribution,
        total_contributions=round(monthly_contribution * years * 12, 2),
        goal_amount=goal_amount,
        probability_of_success=round(prob, 4) if prob is not None else None,
        expected_value=round(float(finals.mean()), 2),
        final_percentiles={
            f"p{p}": round(float(np.percentile(finals, p)), 2)
            for p in (5, 10, 25, 50, 75, 90, 95)
        },
        bands=ProjectionBands(
            dates=dates, p5=bands[5], p25=bands[25],
            p50=bands[50], p75=bands[75], p95=bands[95],
        ),
        assumed_annual_return=round(float(mu * _TRADING_DAYS), 6),
        assumed_annual_volatility=round(float(sigma * np.sqrt(_TRADING_DAYS)), 6),
    )
    return projection, finals


def get_risk(
    data_dir: str,
    years: float = 20.0,
    goal_amount: float | None = None,
    monthly_contribution: float = 0.0,
    num_simulations: int = 2000,
    portfolio: str | None = None,
) -> RiskReport:
    """Risk metrics plus a Monte Carlo projection for the portfolio.

    ``portfolio`` scopes the report to one account; ``None`` spans every
    portfolio. The weights are read off the scoped snapshot, so the
    projection is fitted to that account's actual mix rather than being
    resliced from an aggregate fit.

    Raises:
        ValueError: no priced holdings, no usable return history, an
            out-of-range parameter, or an unknown ``portfolio``.
    """
    if years <= 0 or years > 60:
        raise ValueError("years must be between 0 and 60.")
    if num_simulations < 100 or num_simulations > 20000:
        raise ValueError("num_simulations must be between 100 and 20000.")
    if monthly_contribution < 0:
        raise ValueError("monthly_contribution cannot be negative.")

    from src.services.dashboard import get_snapshot

    snap = get_snapshot(data_dir, portfolio=portfolio)
    if not snap.holdings:
        raise ValueError("No priced holdings — nothing to model.")

    weights: dict[str, float] = {}
    for h in snap.holdings:
        weights[h.ticker] = weights.get(h.ticker, 0.0) + h.market_value

    port, covered, notes = _portfolio_returns(data_dir, weights)
    if port.empty:
        raise ValueError(
            "No usable return history for these holdings. "
            "Run 'invest-monitor collect' to fetch prices first."
        )

    metrics = _metrics(port)
    projection, _ = _simulate(
        start_value=snap.market_value,
        mu=float(port.mean()),
        sigma=float(port.std()),
        years=years,
        monthly_contribution=monthly_contribution,
        num_simulations=num_simulations,
        goal_amount=goal_amount,
    )

    return RiskReport(
        market_value=snap.market_value,
        metrics=metrics,
        projection=projection,
        holdings_covered=covered,
        holdings_total=len(weights),
        data_notes=notes,
    )


__all__ = ["get_risk", "simulate_paths"]

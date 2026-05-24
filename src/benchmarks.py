"""Named benchmark portfolios for comparison against the user's holdings.

Each benchmark is a weighted basket of public ETF proxies so we can pull
real historical prices via yfinance (`Collector.collect_prices`) and the
existing price store. Benchmark daily returns are weighted-sum of proxy
daily returns, renormalised on each date over whichever proxies have data
(so a benchmark with one freshly-listed proxy still produces a clean series
on dates where the older proxies have history).

Used by the Performance Attribution section of the Multi-Portfolio Dashboard
to overlay benchmarks on the cumulative-return chart and compute deltas vs
each portfolio.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.database import Database


@dataclass(frozen=True)
class Benchmark:
    name: str
    description: str
    weights: dict[str, float]  # ticker → weight; should sum to ~1.0

    @property
    def proxies(self) -> list[str]:
        return list(self.weights.keys())


BENCHMARKS: dict[str, Benchmark] = {
    "60/40 Classic": Benchmark(
        name="60/40 Classic",
        description="60% US Total Market, 40% US Aggregate Bond. The textbook balanced portfolio.",
        weights={"VTI": 0.60, "BND": 0.40},
    ),
    "All Seasons (Dalio)": Benchmark(
        name="All Seasons (Dalio)",
        description=(
            "Ray Dalio's All-Weather / All-Seasons recipe: balanced across "
            "growth and inflation regimes. 30% stocks, 55% bonds (mixed "
            "duration), 15% real assets (gold + commodities)."
        ),
        weights={
            "VTI":  0.30,  # US Total Stock Market
            "TLT":  0.40,  # 20+ year Treasuries
            "IEI":  0.15,  # 3-7 year Treasuries
            "GLD":  0.075, # Gold
            "DBC":  0.075, # Diversified Commodities
        },
    ),
    "Golden Butterfly": Benchmark(
        name="Golden Butterfly",
        description=(
            "PortfolioCharts: 20% each across Large Cap, Small Cap Value, "
            "Long Bonds, Short Bonds, Gold. Designed for low drawdown with "
            "reasonable returns across macro regimes."
        ),
        weights={
            "VTI":  0.20,  # Total US Market
            "IJS":  0.20,  # S&P SmallCap 600 Value
            "TLT":  0.20,  # Long Treasuries
            "SHY":  0.20,  # 1-3 year Treasuries
            "GLD":  0.20,  # Gold
        },
    ),
    "Permanent Portfolio (Browne)": Benchmark(
        name="Permanent Portfolio (Browne)",
        description=(
            "Harry Browne's 4-way split: equal weights on Stocks, Long Bonds, "
            "Gold, and Cash. One quadrant performs in any economic regime."
        ),
        weights={
            "VTI":  0.25,  # Stocks
            "TLT":  0.25,  # Long Treasuries
            "GLD":  0.25,  # Gold
            "SHY":  0.25,  # Short-term Treasuries (cash proxy)
        },
    ),
    "Risk Parity (simple)": Benchmark(
        name="Risk Parity (simple)",
        description=(
            "Stylised inverse-volatility weighting across Stocks / Bonds / "
            "Gold so each asset contributes roughly equal risk. Bond-heavy "
            "because bond vol is much lower than equity vol."
        ),
        weights={
            "VTI":  0.25,
            "TLT":  0.55,
            "GLD":  0.20,
        },
    ),
    "3-Fund Bogle": Benchmark(
        name="3-Fund Bogle",
        description=(
            "John Bogle's three-fund recipe: US Total Market, International "
            "Total Market, US Aggregate Bond. Cheap, broad, simple."
        ),
        weights={
            "VTI":  0.60,
            "VXUS": 0.20,  # International ex-US
            "BND":  0.20,
        },
    ),
    "Coffeehouse (Schultheis)": Benchmark(
        name="Coffeehouse (Schultheis)",
        description=(
            "Bill Schultheis's 7-way split: equal slices across US Large / "
            "Value / Small / Small-Value, International, REITs, plus 40% Bonds."
        ),
        weights={
            "VTI":  0.10,  # Total US (LargeCap proxy)
            "VTV":  0.10,  # Large Value
            "VB":   0.10,  # Small Cap
            "VBR":  0.10,  # Small Value
            "VXUS": 0.10,  # International
            "VNQ":  0.10,  # US REITs
            "BND":  0.40,  # US Aggregate Bonds
        },
    ),
    "Larry Portfolio (Swedroe)": Benchmark(
        name="Larry Portfolio (Swedroe)",
        description=(
            "Larry Swedroe's barbell: a small slug of high-risk equity factor "
            "(small-cap value) plus heavy intermediate bonds. Targets equity-"
            "like returns with materially lower drawdown."
        ),
        weights={
            "IJS":  0.30,  # SmallCap Value
            "IEI":  0.70,  # 3-7 year Treasuries
        },
    ),
}


def all_proxy_tickers() -> list[str]:
    """Union of every proxy ticker across all benchmarks."""
    seen: dict[str, None] = {}
    for b in BENCHMARKS.values():
        for t in b.proxies:
            seen[t] = None
    return list(seen.keys())


def benchmark_daily_returns(
    benchmark: Benchmark,
    db: Database,
    start_date: str | None = None,
) -> pd.Series:
    """Return the weighted daily-return series for a benchmark.

    For each date, weights are renormalised across the proxies that have a
    valid (non-NaN) return on that date — so a benchmark whose newest proxy
    has shorter history (e.g. VXUS only since 2011) still produces a clean
    series on older dates, driven by the older proxies at their relative
    weights.
    """
    prices = db.get_historical_prices(benchmark.proxies, start_date=start_date)
    if prices.empty:
        return pd.Series(dtype=float)

    prices = prices.sort_index()
    # Keep only columns we actually have data for.
    available = [t for t in benchmark.proxies if t in prices.columns]
    if not available:
        return pd.Series(dtype=float)

    w = np.array([benchmark.weights[t] for t in available], dtype=float)
    rets = prices[available].pct_change()
    valid = rets.notna()
    row_weight = valid.astype(float).mul(w, axis=1).sum(axis=1)
    contrib    = rets.fillna(0.0).mul(w, axis=1).sum(axis=1)
    daily = (contrib / row_weight).where(row_weight > 0).dropna()
    daily.name = benchmark.name
    return daily


def benchmark_cumulative(
    benchmark: Benchmark,
    db: Database,
    start_date: str | None = None,
) -> pd.Series:
    """Cumulative return series rebased to 0 at `start_date` (or first
    available date if start_date is None)."""
    daily = benchmark_daily_returns(benchmark, db, start_date=start_date)
    if daily.empty:
        return daily
    return (1.0 + daily).cumprod() - 1.0


def benchmark_stats(
    benchmark: Benchmark,
    db: Database,
    start_date: str | None = None,
) -> dict:
    """Period return, annualised vol, max drawdown for a benchmark."""
    daily = benchmark_daily_returns(benchmark, db, start_date=start_date)
    if daily.empty or len(daily) < 2:
        return {"period_return": None, "vol_annualised": None, "max_drawdown": None}
    cum = (1.0 + daily).cumprod()
    cum_return = float(cum.iloc[-1] - 1.0)
    vol = float(daily.std() * np.sqrt(252.0))
    cummax = cum.cummax()
    dd = (cum - cummax) / cummax
    return {
        "period_return": cum_return,
        "vol_annualised": vol,
        "max_drawdown": float(dd.min()),
    }

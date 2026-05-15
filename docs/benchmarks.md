# Benchmark Portfolios

Eight built-in named recipes for "what should I compare my portfolio against?". Each is a weighted basket of public ETF proxies, so historical returns come from yfinance + the existing price store. Use them as overlays on the [Performance Attribution](performance-attribution.md) cumulative-return chart, with a "vs benchmark" delta table per portfolio.

## The eight recipes

| Benchmark | Weights | Spirit |
|---|---|---|
| **60/40 Classic** | 60% VTI + 40% BND | The textbook |
| **All Seasons (Dalio)** | 30% VTI / 40% TLT / 15% IEI / 7.5% GLD / 7.5% DBC | Balanced across growth + inflation regimes |
| **Golden Butterfly** | 20% each: VTI / IJS / TLT / SHY / GLD | Low drawdown, decent returns across all regimes |
| **Permanent Portfolio (Browne)** | 25% each: VTI / TLT / GLD / SHY | One quadrant performs in any environment |
| **Risk Parity (simple)** | 25% VTI / 55% TLT / 20% GLD | Inverse-vol weights — roughly equal risk contribution |
| **3-Fund Bogle** | 60% VTI + 20% VXUS + 20% BND | Cheap, broad, simple |
| **Coffeehouse (Schultheis)** | 10% each: VTI / VTV / VB / VBR / VXUS / VNQ + 40% BND | 7-way diversified + heavy bonds |
| **Larry Portfolio (Swedroe)** | 30% IJS + 70% IEI | Barbell: small-cap value + intermediate Treasuries |

Total unique proxy tickers across all eight: 13. Defined in `src/benchmarks.py`.

## First-time setup

Benchmark proxies need price history fetched:

```bash
invest-monitor benchmarks list             # show the table
invest-monitor benchmarks fetch            # default 10y of history
invest-monitor benchmarks fetch --period 5y
invest-monitor benchmarks fetch --period max
```

This pulls all 13 unique proxy tickers in one shot, into `data/prices/*.parquet`. Cached and reused across all benchmarks that share a proxy.

## How returns are computed

`benchmark_daily_returns(b, db)` returns the weighted-sum daily-return series across the proxies. On each date, weights are **renormalised across whichever proxies have a valid return that day** — so a benchmark whose newest proxy has shorter history (e.g. VXUS only since 2011) still produces a clean series on older dates, driven by the older proxies at their relative weights.

`benchmark_cumulative(b, db, start_date)` rebases to 0 at `start_date`. `benchmark_stats(b, db, start_date)` returns period return, annualised vol, and max drawdown over the window.

## Dashboard overlay

In **Performance Attribution**:

1. **Overlay benchmarks** multiselect appears above the cumulative-return chart. Pick any subset.
2. Each selected benchmark renders as a **dashed line** on the chart, rebased to the same window start as your portfolios.
3. **Benchmark stats over the same window** table — one row per selected benchmark with Period Return, Annualised Vol, Max Drawdown, proxy count.
4. **vs {primary benchmark}** delta table — for each portfolio: Period Return + `(portfolio return − primary benchmark return)`. The primary benchmark is whichever you picked first in the multiselect.

!!! tip "Pairing benchmarks with regime presets"
    The [Wealth Projection](wealth-projection.md) section's MC has historical regime presets. Combine them — e.g. flip the preset to "2000s Dual Shock" and see how the All Seasons benchmark would have fared in that decade vs your portfolio's MC distribution.

## Reading the comparison

The eight benchmarks span the realistic envelope of "what could I have done":

- **Larry Portfolio** sits at the low-risk end — lowest vol and drawdown, lowest absolute return.
- **3-Fund Bogle / 60/40** sit at the high-equity end — highest returns over equity bulls, deepest drawdowns in equity bears.
- **Permanent / Golden Butterfly** are the diversification recipes — lower vol than 60/40 with comparable long-run returns.
- **All Seasons / Risk Parity** are bond-heavy; they shine in 1970s-style inflation **only if Treasuries-as-inflation-hedge thesis holds** for the period — under modern positive-stock/bond correlation regimes they underperform.

So when comparing your portfolio: pick 2–3 benchmarks that bracket the strategy you *think* you're running. If you're aiming for a 60/40 mix, overlay 60/40 + Permanent + Golden Butterfly to see the trade-off space.

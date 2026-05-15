# Performance Attribution

Daily security-level, portfolio-level, and per-position contribution metrics, persisted to parquet for time-series analysis.

## Computation modes

`AttributionEngine.refresh_all()` chooses one of two modes per portfolio automatically:

| Mode | When it's used | What it computes |
|---|---|---|
| **v2 — trade replay** | `trades.parquet` has any rows for the portfolio | Pivots trades into a `(date × ticker)` delta matrix (BUY +, SELL −), reindexes to the price calendar (off-calendar trades snap to the next trading day), `cumsum` to get running positions, multiplies by daily prices for `(date, ticker)` values. Each historical date uses the *actual* holdings on that date. |
| **v1 — static current** | No trades recorded | Uses today's positions across the whole price history — "if I had held this portfolio over time …". |

The Refresh-metrics success message lists which mode each portfolio used. To upgrade a v1 portfolio to v2: record historical trades in the **📋 Trades** tab, then click **Refresh metrics**.

## Daily metrics stores

| File | Schema |
|---|---|
| `daily_security_metrics.parquet`  | `date, ticker, price, daily_return, cum_return, rolling_vol_21d` |
| `daily_portfolio_metrics.parquet` | `date, portfolio_name, total_value, daily_return, cum_return, rolling_vol_21d, drawdown, max_drawdown` |
| `daily_attribution.parquet`       | `date, portfolio_name, ticker, weight, position_return, contribution_to_return, asset_type, sector` |

Brinson invariant: `Σ contribution_to_return` over a date for one portfolio = the portfolio's `daily_return` on that date (within float precision).

## Refreshing

| Channel | Behaviour |
|---|---|
| **Sidebar "Refresh metrics" button** | Always visible. Recomputes for every portfolio, reports modes used. |
| `invest-monitor metrics refresh`     | One-shot. Incremental: re-walks the last 30 days from the latest stored date. |
| `invest-monitor metrics refresh --full` | Recompute the entire history. |
| `invest-monitor metrics refresh --portfolio "Name"` | Scope to one portfolio. |
| `invest-monitor metrics refresh --from 2024-01-01` | Recompute from a date forward. |

The **collect_prices** + **refresh_attribution** [production jobs](production.md) wire this up for automated daily updates.

## Dashboard view

In **Multi-Portfolio Dashboard → Performance Attribution**:

- **Period selector**: 1M / 3M / 6M / 1Y / YTD / All.
- **Overlay benchmarks** multiselect (see [Benchmarks](benchmarks.md)).
- Cumulative-return chart, rebased to the start of the selected window.
- Drawdown chart (peak-to-trough, since inception).
- End-of-period KPI table per portfolio: Period Return, 21-day annualised vol, Current Drawdown, Max Drawdown (since inception), Latest Value.
- Benchmark stats table (when overlays selected): Period Return, Vol, Max Drawdown over the same window.
- "vs {primary benchmark}" delta table: portfolio period return − benchmark period return.
- **Top 10 contributors** + **Top 10 detractors** over the window (Σ daily contributions per ticker, with asset_type and sector tags).
- **Cumulative contribution by asset type** stacked area — shows which asset classes drove returns over time.

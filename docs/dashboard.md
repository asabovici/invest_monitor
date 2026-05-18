# Dashboard

```bash
streamlit run src/app.py
```

The sidebar offers three top-level views: **Multi-Portfolio Dashboard**, **Single Portfolio**, and **⚙️ Production**. The sidebar also has:

- **🎭 Demo mode** toggle (switches every read to `data_demo/`).
- Portfolio selector + **New Empty Portfolio** expander + **Import from CSV** expander.
- **Refresh metrics** — always visible. Recomputes `daily_*.parquet` for every portfolio and reports which used v2 trade-replay vs v1 static-current.
- **Collect Prices** (visible after a portfolio is open) — fetches yfinance history for the chosen period.

## Single Portfolio (nine tabs)

| Tab | Contents |
|-----|----------|
| 📊 **Overview** | Position table with current prices, P&L, allocation donut. **🔍 Lookthrough toggle** disaggregates ETF/Fund positions. |
| 📈 **Price History** | Normalised price chart, cumulative returns, daily returns. |
| 🥧 **Exposure** | Asset-type pie + sector bar with the **🔍 Lookthrough toggle** (default ON). Groups by (Type, Sector). |
| ⚠️ **Risk** | Volatility, VaR, correlation heatmap, return distribution, covariance heatmap. **Sector Stress Test**: Custom / Implied-from-driver-sector / 7 named scenarios. |
| 💵 **Income** | Annual income KPI, asset-type donut, payment-frequency-aware 12-month schedule, per-position detail. |
| ✏️ **Positions** | Editable position table; add new positions. |
| 🏢 **Security Master** | Edit asset metadata (name, type, sector, currency, **Income Rate**, **Payment Frequency**). |
| 📋 **Trades** | Record BUY/SELL trades; view trade history. Drives v2 attribution reconstruction. |
| 🔍 **Lookthrough** | Upload vendor holdings CSV **or** click **Fetch Profile from yfinance** for sector-level fallback. |

## Multi-Portfolio Dashboard

Top to bottom:

1. **Group filter** (appears once any group exists, see [Portfolio Groups](portfolio-groups.md)) — selectbox to scope the dashboard to one group's members. Adjacent **"View as combined portfolio"** toggle merges those members into one synthetic entity for everything below.
1. **KPI strip** — Portfolios, Positions, Total Cost, Current Value, Unrealised P&L (with %).
2. **Aggregate Exposure** — donut + sector bar + Top 15 underlying-exposures table, with the **🔍 Lookthrough toggle**. See [Lookthrough](lookthrough.md).
3. **Summary** table — 1M/3M/6M/1Y returns, vol, VaR, drawdowns per portfolio + a merged-TOTAL row computed from a synthetic combined portfolio.
4. **Cumulative-return / risk / drawdown** comparison charts.
5. **Income Projection** — annual / monthly / yield KPIs, per-portfolio table, donut by asset type, payment schedule, per-position detail. See [Income & SWR](income-and-swr.md).
6. **Performance Attribution** — cum-return + drawdown + top contributors/detractors + cumulative contribution by asset type. Benchmark overlay supported. See [Performance Attribution](performance-attribution.md) + [Benchmarks](benchmarks.md).
7. **Wealth Projection** — Deterministic / Monte Carlo / Safe Withdrawal Rate. See [Wealth Projection](wealth-projection.md).
8. **🤖 Ask the Agents** — embedded chat panel with Risk / Wealth / Research tabs. Each agent is lazily instantiated and keeps its own history, scoped per mode (live vs demo). See [AI Agents](ai-agents.md).

## ⚙️ Production view

A monitoring panel for the scheduled-job runner — see [Production](production.md).

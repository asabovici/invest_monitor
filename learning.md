# invest_monitor — Codebase Learnings

## Overview

`invest_monitor` is a personal portfolio monitoring and risk analysis tool. It stores holdings as Parquet files, fetches historical prices via yfinance, exposes a Streamlit dashboard, a Click CLI, and three Claude-powered conversational agents (risk, wealth, research).

---

## Architecture

```
CSV sources → manual ingestion / dashboard upload → Parquet files
ETF vendor CSVs → Ingester.parse_fund_holdings_csv() → fund_holdings.parquet
                                                              ↑
                                                     Collector (yfinance)
                                                              ↓
                                          Database (parquet read/write via pandas + DuckDB)
                                         /           |            \
                                  Reporting       CLI (Click)    Agents (Claude Opus 4.6)
                                  Engine               |              |
                                      \            tabulate      Streamlit (app.py)
                                       \___________________________________/
```

---

## Data Layer

All data lives under `data/` as Parquet files. **`*.parquet` and `*.csv` are gitignored.**

```
data/
├── assets.parquet         — ticker, name, asset_type, currency, sector
├── portfolios.parquet     — name, created_at
├── positions.parquet      — portfolio_name, ticker, quantity, cost_basis (PER SHARE)
├── constituents.parquet   — parent_ticker, constituent_ticker, weight (legacy inline look-through)
├── fund_holdings.parquet  — fund_ticker, as_of_date, holding_ticker, holding_name, weight, sector, asset_type
└── prices/
    └── {TICKER}.parquet   — date index, price column
```

### CRITICAL: cost_basis is per-share

`positions.parquet.cost_basis` = cost **per share**, not total.
`Portfolio.total_cost()` = Σ (quantity × cost_basis).
Storing total cost basis causes double-multiplication. This bug was hit in April 2026 (GOVT showed $110M instead of $49,992).

### portfolios.parquet must stay in sync with positions.parquet

`invest-monitor portfolio list` reads portfolios.parquet. It is NOT auto-populated when writing positions.parquet. Must write both together or the list command returns nothing. `Database.save_portfolio()` handles both atomically.

### fund_holdings.parquet

Stores monthly ETF/fund holdings snapshots uploaded by the user. Keyed by `(fund_ticker, as_of_date)`. Used by the Exposure tab to disaggregate ETF/Fund positions into underlying sector/type buckets. Managed via:
- `Database.save_fund_holdings(fund_ticker, as_of_date, holdings_df)` — upserts a snapshot
- `Database.get_fund_holdings(fund_ticker, as_of_date=None)` — returns latest if no date given
- `Database.list_fund_holdings_dates(fund_ticker)` — all snapshot dates, newest first
- `Database.delete_fund_holdings(fund_ticker, as_of_date)` — removes a snapshot

### String columns and NaN dtype issue

When a string column (e.g. `sector`, `currency`) is all-NaN in a parquet file, pandas reads it back as `float64`. This breaks Streamlit's `TextColumn` config with `ColumnDataKind.FLOAT` error. Fix: `df[col] = df[col].fillna("").astype(str)` before passing to `st.data_editor`. Applied in `get_all_assets()` and before building `pos_df` in the Positions tab.

### Asset type mapping (CSV → enum)

| CSV `asset_class` | `AssetType` enum value |
|---|---|
| Equity | Stock |
| ETF | ETF |
| Fixed Income | Bond |
| Mutual Fund | Fund |
| Cash | Cash |

---

## Active Portfolios

| Name | Description |
|------|-------------|
| SCHAB | Main Schwab brokerage account (~29 positions) |
| ESPP | PRU employee stock purchase plan + BLK |
| MARCUS | Marcus savings (CD + cash) |

### PRU ESPP data source

PRU cost basis comes from `data/pru_espp_trades.csv` (individual quarterly purchases), not the summary row in `positions_data_20260215.csv`. Weighted average: `sum(quantity × cost_per_share) / sum(quantity)` ≈ 89.92/share.

---

## Module Breakdown

### `src/models.py`

| Class | Key fields |
|-------|-----------|
| `AssetType` | Enum: Stock, Bond, ETF, Fund, Cash, Crypto |
| `Asset` | ticker, name, asset_type, currency, sector, constituents |
| `Constituent` | ticker, weight (0–1), name |
| `Position` | asset, quantity, **cost_basis (per share)** |
| `Portfolio` | name, positions; `total_cost()` = Σ quantity×cost_basis |

`Asset.is_composite()` returns `True` if the asset has constituents (legacy inline look-through). The preferred look-through mechanism is now `fund_holdings.parquet`.

### `src/database/database.py`

Key methods:
- `add_asset(asset)` — upserts into assets.parquet + constituents.parquet
- `save_portfolio(portfolio)` — upserts portfolio metadata + replaces all its positions
- `get_portfolio(name)` — DuckDB join of positions + assets → full Portfolio object
- `list_portfolios()` — reads portfolios.parquet ordered by created_at DESC
- `get_historical_prices(tickers, start_date)` — pivot of per-ticker price files → date×ticker DataFrame
- `get_all_assets()` — reads assets.parquet, casts name/sector/currency to str to prevent float dtype
- `save_fund_holdings(fund_ticker, as_of_date, df)` — upserts holdings snapshot
- `get_fund_holdings(fund_ticker, as_of_date=None)` — returns latest snapshot if no date
- `list_fund_holdings_dates(fund_ticker)` — snapshot dates newest first
- `delete_fund_holdings(fund_ticker, as_of_date)` — removes snapshot
- `record_trade(...)` — appends to trades.parquet + updates positions via avg-cost blending (BUY) or quantity reduction (SELL)
- `update_positions_direct(portfolio_name, rows)` — bulk-replace positions for a portfolio

### `src/data/ingestion.py`

Two parsers:

**`Ingester.load_portfolio_from_csv(file_path, portfolio_name)`**
Columns: `Ticker, Name, Type, Quantity, CostBasis` (per share). Optional: `Currency, Sector, ConstituentTickers, ConstituentWeights`.

**`Ingester.parse_fund_holdings_csv(content: bytes, fund_ticker: str)`**
Auto-detects ETF vendor CSV format (iShares, Vanguard, etc.):
- Finds the real header row by scanning for rows with ≥3 comma-separated tokens and ≥2 alphabetic words
- Fuzzy-matches columns: ticker (`Ticker`, `Symbol`, `ISIN`…), name (`Name`, `Holding`…), weight (`Weight (%)`, `% of fund`…), sector, asset class
- Normalises weights to fractions (divides by 100 if sum > 1.5)
- Fills blank tickers with slugified name
- Returns: `holding_ticker, holding_name, weight, sector, asset_type`

### `src/collector.py`

`Collector.update_all_assets(period)` — fetches yfinance close prices for all tickers in assets.parquet. `collect_prices(tickers, period)` — same for a specific list.

### `src/reporting.py`

| Method | Returns |
|--------|---------|
| `get_portfolio_exposure(portfolio)` | DataFrame grouped by Type+Sector |
| `calculate_returns(tickers, start_date)` | Daily pct_change DataFrame |
| `calculate_cumulative_returns(tickers, start_date)` | Cumulative return series rebased to 0 at start |
| `get_portfolio_risk_metrics(portfolio)` | Dict: Volatility, Historical VaR 95%, Monte Carlo VaR 95%, Covariance Matrix |
| `calculate_historical_var(returns, confidence_level)` | Empirical percentile |
| `calculate_monte_carlo_var(returns, confidence_level)` | Parametric simulation |

### `src/app.py` — Streamlit dashboard

Two views toggled from sidebar radio:

**Multi-Portfolio Dashboard** — always available:
- Summary table: all portfolios × (returns 1M/3M/6M/1Y, vol, VaR 95%/99%, max drawdown, current drawdown)
- Returns, risk, and drawdown comparison bar charts
- Wealth Projection: configurable annual return % per asset class, 1–3 time periods, horizon up to 50y; line chart + milestone table

**Single Portfolio** — requires portfolio selection. Eight tabs:

| Tab | Key details |
|-----|-------------|
| Overview | Position table with P&L, allocation donut |
| Price History | Normalised prices, cumulative returns, daily returns |
| Exposure | Asset-type pie + sector bar. ETF/Fund positions → disaggregated via `fund_holdings.parquet` if snapshots exist; falls back to legacy constituents or treats as opaque. |
| Risk | Volatility/VaR metrics, correlation heatmap, return distribution with VaR line, covariance matrix |
| Positions | Editable `st.data_editor` table; add new positions via form; Save replaces all positions |
| Security Master | Edit name/type/sector/currency per asset; Ticker is read-only key |
| Trades | Record BUY/SELL trades (avg-cost blending on BUY); trade history table |
| Lookthrough | Upload ETF/fund vendor CSV → choose as-of date → import; view/delete snapshots; sector breakdown chart; holdings table; portfolio contribution table |

### `src/agent/` — Three Claude Opus 4.6 agents

| Agent | CLI | Purpose |
|-------|-----|---------|
| `RiskAgent` | `invest-monitor agent` | Risk measurement, stress testing, scenario analysis (13 skills) |
| `WealthAgent` | `invest-monitor wealth` | P&L, Sharpe/Sortino, rebalancing, goal projection, tax-loss harvesting (9 skills) |
| `ResearchAgent` | `invest-monitor research` | Capital deployment within constraints; uses live web search + portfolio simulation (5 skills + server-side web_search) |

All agents: multi-turn conversation, `client.beta.messages.tool_runner`, thinking blocks stored separately from history to avoid issues on subsequent turns.

---

## Multi-Portfolio Metrics: compute_portfolio_metrics()

Key implementation detail in `app.py`:
- Uses `prices[available].dropna(how="any")` before `.dot(w)` — avoids NaN propagation into the weighted portfolio series
- Renormalizes weights to only the tickers with price data (`w = w_raw / w_raw.sum()`)
- Returns `None` if `port_series` is empty or has < 2 points — shown as "No price data" in the summary table, not an error

---

## Exposure Tab: Lookthrough Logic

When computing exposure with current prices:
1. For each position, check if `asset_type` is ETF or Fund
2. If yes, call `db.get_fund_holdings(ticker)` — returns the latest snapshot
3. If holdings exist: expand each holding row into `(type, sector, value)` using `holding.weight × fund_value`
4. If no holdings: fall back to legacy `Asset.constituents` (inline look-through) or treat as opaque
5. Aggregate all rows by `(Type, Sector)` → drives pie chart, bar chart, and exposure table

---

## Risk Methodology

- **Volatility** — annualized std dev of daily returns × √252
- **Historical VaR** — empirical percentile of observed daily returns
- **Monte Carlo VaR** — parametric: draw 10,000 samples from N(mean, std), take percentile
- **Cumulative return** — `prices / prices.iloc[0] - 1`, rebased to 0 at first available date
- **Max drawdown** — `(price - cummax) / cummax`, minimum over full history
- **Portfolio weighting** — dollar-weighted by `quantity × cost_basis`

---

## Known Issues / Watch-outs

- **Run from project root** — `data/` path is relative; running from elsewhere creates a new empty store
- **`Type` values must match AssetType enum exactly** — `Stock`, `ETF`, `Bond`, `Fund`, `Cash`, `Crypto`
- **MARCUS + cash instruments have no price data** — `compute_portfolio_metrics` returns None; shown as "No price data" in multi-portfolio view
- **`collect` before `report`/agent** — risk metrics need price data; agent will tell user to run collect if missing
- **`portfolios.parquet` must be kept in sync with `positions.parquet`**
- **All-NaN string columns read back as float64** — breaks Streamlit TextColumn; fix with `.fillna("").astype(str)` before `st.data_editor`

---

## Setup

```bash
uv sync          # install deps
uv run invest-monitor portfolio list    # verify portfolios
streamlit run src/app.py               # launch dashboard
invest-monitor agent                   # launch risk agent (needs ANTHROPIC_API_KEY)
```

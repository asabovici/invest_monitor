# invest_monitor — Codebase Learnings

## Overview

`invest_monitor` is a personal portfolio monitoring and risk analysis tool. It stores holdings as Parquet files, fetches historical prices via yfinance, exposes a Streamlit dashboard, a Click CLI, and a Claude-powered conversational risk agent.

---

## Architecture

```
CSV sources → manual ingestion scripts → Parquet files
                                              ↑
                                         Collector (yfinance)
                                              ↓
                              Database (parquet read/write)
                             /           |            \
                      Reporting       CLI (Click)    Agent (Claude Opus 4.6)
                      Engine               |              |
                          \            tabulate      Streamlit (app.py)
                           \___________________________________/
```

---

## Data Layer

All data lives under `data/` as Parquet files. **`*.parquet` and `*.csv` are gitignored.**

```
data/
├── securities.parquet     — security master (ticker, cusip, name, sector, asset_type, exchange, currency)
├── assets.parquet         — subset used by the DB layer (ticker, name, asset_type, currency, sector)
├── portfolios.parquet     — portfolio registry (name, created_at)
├── positions.parquet      — holdings (portfolio_name, ticker, quantity, cost_basis)
├── constituents.parquet   — ETF/Fund look-through (parent_ticker, constituent_ticker, weight)
└── prices/
    └── {TICKER}.parquet   — per-ticker daily close prices (date index, price column)
```

### CRITICAL: cost_basis is per-share

`positions.parquet.cost_basis` stores **cost per share**, NOT total cost basis.
`Portfolio.total_cost()` computes `sum(quantity × cost_basis)`.
Storing total cost basis there causes double-multiplication (e.g. GOVT: 2220 shares × $49,992 = $110M instead of $49,992).

### portfolios.parquet must stay in sync

`invest-monitor portfolio list` reads from `portfolios.parquet`. If you repopulate `positions.parquet` without also writing `portfolios.parquet`, the list command returns nothing. Always write both together.

### Asset type mapping

The securities CSV uses different labels than the `AssetType` enum:

| CSV `asset_class` | `AssetType` enum value |
|-------------------|------------------------|
| Equity            | Stock                  |
| ETF               | ETF                    |
| Fixed Income      | Bond                   |
| Mutual Fund       | Fund                   |
| Cash              | Cash                   |

---

## Active Portfolios

| Name   | Description                                      |
|--------|--------------------------------------------------|
| SCHAB  | Main Schwab brokerage account (~29 positions)    |
| ESPP   | PRU employee stock purchase plan + BLK           |
| MARCUS | Marcus savings (CD + cash)                       |

### PRU ESPP data source

PRU position in the ESPP portfolio comes from `data/pru_espp_trades.csv`, not the summary row in `positions_data_20260215.csv`. The trades file has individual quarterly purchases; cost_basis_per_share is computed as a weighted average: `sum(quantity × cost_per_share) / sum(quantity)`.

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

### `src/database/database.py`

Key methods:
- `save_portfolio(portfolio)` — upserts portfolio + replaces all its positions
- `get_portfolio(name)` — DuckDB join of positions + assets; returns full Portfolio object
- `list_portfolios()` — reads portfolios.parquet ordered by created_at DESC
- `get_historical_prices(tickers, start_date)` — pivot of per-ticker price files → date×ticker DataFrame

### `src/data/ingestion.py`

`Ingester.load_portfolio_from_csv()` expects columns: `Ticker, Name, Type, Quantity, CostBasis` (CostBasis = per share). Optional: `Currency, Sector, ConstituentTickers, ConstituentWeights`.

### `src/collector.py`

`Collector.update_all_assets(period)` — fetches yfinance close prices for all tickers in assets.parquet. `collect_prices(tickers, period)` — same but for a specific list.

### `src/reporting.py`

| Method | Returns |
|--------|---------|
| `get_portfolio_exposure(portfolio)` | DataFrame grouped by Type+Sector |
| `calculate_returns(tickers, start_date)` | Daily pct_change DataFrame |
| `calculate_cumulative_returns(tickers, start_date)` | Cumulative return series rebased to 0 at start |
| `get_portfolio_risk_metrics(portfolio)` | Dict: Volatility, Historical VaR 95%, Monte Carlo VaR 95%, Covariance Matrix |
| `calculate_historical_var(returns, confidence_level)` | Empirical percentile |
| `calculate_monte_carlo_var(returns, confidence_level)` | Parametric simulation |

### `src/cli.py`

| Command | Description |
|---------|-------------|
| `invest-monitor load <csv> [--name]` | Ingest portfolio CSV → DB |
| `invest-monitor collect [--period] [--portfolio]` | Fetch prices via yfinance |
| `invest-monitor report <name>` | Print exposure + risk metrics |
| `invest-monitor portfolio list` | List saved portfolios |
| `invest-monitor portfolio delete <name>` | Remove a portfolio |
| `invest-monitor agent [--portfolio] [--query]` | Launch Claude risk agent |

### `src/agent/agent.py`

`RiskAgent` — multi-turn Claude Opus 4.6 conversation with adaptive thinking. Uses `client.beta.messages.tool_runner`. Stores only text (not thinking blocks) in history to avoid issues on subsequent turns.

### `src/agent/skills.py`

Agent tools (all decorated with `@beta_tool`):

| Skill | Purpose |
|-------|---------|
| `list_portfolios` | List all portfolios |
| `get_portfolio_summary` | Full position breakdown with weights |
| `get_risk_metrics` | Volatility, VaR 95% |
| `get_exposure_breakdown` | Exposure by type + sector |
| `check_concentration_risk` | Flag positions above threshold % |
| `get_correlation_matrix` | Pairwise correlations with high-corr alerts |
| `calculate_max_drawdown` | Peak-to-trough drawdown per asset + portfolio |
| `get_price_performance` | Returns over 1M, 3M, 6M, 1Y |
| `get_cumulative_returns` | Cumulative return from start of history (or given date) |
| `list_stress_scenarios` | Available named scenarios |
| `run_stress_test` | Named scenario P&L impact |
| `apply_custom_shock` | Arbitrary shocks by ticker/sector/asset type |
| `simulate_forward` | Monte Carlo forward simulation (percentile outcomes) |

### `src/app.py` — Streamlit dashboard

Two views toggled from sidebar radio:

**Multi-Portfolio Dashboard** — always available:
- Summary table: all portfolios × (returns 1M/3M/6M/1Y, vol, VaR 95%/99%, max drawdown, current drawdown)
- Returns comparison bar chart (grouped by horizon)
- Risk metrics bar chart (Vol, VaR 95%, VaR 99%)
- Drawdown bar chart (max vs current)
- Wealth Projection: configurable growth assumptions per asset class, 1–3 time periods, horizon up to 50y; line chart + milestone table

**Single Portfolio** — requires portfolio selection:
- Overview tab: position table with P&L, allocation donut chart
- Price History tab: normalized price chart, cumulative return chart, daily returns bar chart
- Exposure tab: asset type pie, sector bar, exposure table
- Risk tab: volatility/VaR metrics, correlation heatmap, return distribution with VaR line, covariance matrix

---

## Multi-Portfolio Metrics: compute_portfolio_metrics()

Key implementation detail in `app.py:compute_portfolio_metrics()`:
- Uses `prices[available].dropna(how="any")` before `.dot(w)` to avoid NaN propagation
- Renormalizes weights to only the tickers with price data (`w = w_raw / w_raw.sum()`)
- Returns `None` if `port_series` is empty or has fewer than 2 points — renders as "No price data" in the table

---

## Risk Methodology

- **Volatility** — annualized std dev of daily returns × √252
- **Historical VaR** — empirical percentile of observed daily returns
- **Monte Carlo VaR** — parametric: draw 10,000 samples from N(mean, std), take percentile
- **Cumulative return** — `prices / prices.iloc[0] - 1`, rebased to 0 at the first available date
- **Max drawdown** — `(price - cummax) / cummax`, minimum over full history
- **Portfolio weighting** — dollar-weighted by `quantity × cost_basis`

---

## Known Issues / Watch-outs

- **Run from project root** — `data/` path is relative; running from elsewhere creates a new empty store
- **`Type` values must match AssetType enum exactly** — `Stock`, `ETF`, `Bond`, `Fund`, `Cash`, `Crypto`
- **MARCUS + cash instruments have no price data** — `compute_portfolio_metrics` returns None; shown as "No price data" in multi-portfolio view, not an error
- **`collect` before `report`/agent** — risk metrics need price data; agent will tell user to run collect if missing
- **`portfolios.parquet` must be kept in sync with `positions.parquet`** — they are not auto-synced

---

## Setup

```bash
uv sync          # install deps
uv run invest-monitor portfolio list    # verify portfolios
streamlit run src/app.py               # launch dashboard
invest-monitor agent                   # launch AI risk agent (needs ANTHROPIC_API_KEY)
```

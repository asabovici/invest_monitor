# Onboarding Guide — invest_monitor

Welcome. This document will get you from zero to making changes in the codebase.

---

## What this project does

`invest_monitor` is a personal investment portfolio monitoring tool. You give it a CSV of your holdings, it fetches historical prices from Yahoo Finance, stores everything locally, and produces:

- **Exposure reports** — how much of your portfolio is in each asset type and sector, with lookthrough into ETF/Fund holdings
- **Risk metrics** — volatility, Value-at-Risk (historical and Monte Carlo), covariance matrix, drawdown
- **AI agents** — conversational Claude-powered agents for risk, wealth, and research queries

---

## Setup

**Requirements:** Python 3.14+

```bash
# Clone and enter the project
cd invest_monitor

# Install dependencies (preferred)
uv sync

# Or with pip
pip install -e .
```

The data directory is created automatically at `data/` the first time you run any command. You don't need to set it up manually.

> **Note:** Always run CLI commands from the project root. The data path is relative, so running from a different directory will create a new empty data store in the wrong place.

Requires an `ANTHROPIC_API_KEY` environment variable to use any agent.

---

## Running the tool

```bash
# Launch the Streamlit dashboard (primary interface)
streamlit run src/app.py

# CLI commands
invest-monitor load portfolio.csv --name "My Portfolio"
invest-monitor collect --period 1y
invest-monitor report "My Portfolio"
invest-monitor portfolio list
invest-monitor agent --portfolio "My Portfolio"
invest-monitor wealth --portfolio "My Portfolio"
invest-monitor research --portfolio "My Portfolio"
```

Typical workflow: `load` → `collect` → open dashboard or run agent.

---

## Portfolio CSV format

| Column | Required | Description |
|--------|----------|-------------|
| `Ticker` | Yes | Stock ticker (e.g. `AAPL`) |
| `Name` | Yes | Human-readable name |
| `Type` | Yes | One of: `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `Crypto` |
| `Quantity` | Yes | Number of units held |
| `CostBasis` | Yes | **Cost per share** (not total cost) |
| `Currency` | No | Defaults to `USD` |
| `Sector` | No | e.g. `Technology`, `Healthcare` |

**Example:**

```csv
Ticker,Name,Type,Quantity,CostBasis,Currency,Sector
AAPL,Apple Inc,Stock,10,150.00,USD,Technology
ARTY,iShares Thematic ETF,ETF,50,25.00,USD,
```

---

## Codebase map

```
src/
├── app.py           — Streamlit dashboard (primary UI)
├── cli.py           — Click CLI entry point
├── models.py        — Domain objects: Asset, Position, Portfolio, Constituent, AssetType
├── collector.py     — Fetches prices from Yahoo Finance (yfinance)
├── reporting.py     — Risk and exposure calculations
├── database/
│   └── database.py  — Parquet-backed data store
├── data/
│   └── ingestion.py — Portfolio CSV + ETF holdings CSV parsers
└── agent/
    ├── agent.py          — RiskAgent
    ├── skills.py         — Risk agent tools
    ├── wealth_agent.py   — WealthAgent
    ├── wealth_skills.py  — Wealth agent tools
    ├── research_agent.py — ResearchAgent
    └── research_skills.py
```

---

## How the pieces connect

### Loading a portfolio (`cli load` or dashboard upload)

```
Ingester.load_portfolio_from_csv()
    reads CSV row by row
    creates Asset objects
    calls Database.add_asset() for each
    calls Database.save_portfolio()
    returns Portfolio
```

### Collecting prices (dashboard or `cli collect`)

```
Collector.update_all_assets()
    queries all tickers from assets.parquet
    calls yfinance.download() in batches
    calls Database.save_prices() per ticker
```

### ETF lookthrough (`Ingester.parse_fund_holdings_csv()`)

```
User uploads vendor holdings CSV in the Lookthrough tab
    → Ingester.parse_fund_holdings_csv()
        auto-detects header row (skips vendor metadata lines)
        fuzzy-matches columns for ticker/name/weight/sector/asset class
        normalises weights to fractions
    → Database.save_fund_holdings(fund_ticker, as_of_date, df)
        stored in fund_holdings.parquet keyed by (fund_ticker, as_of_date)

Exposure tab reads Database.get_fund_holdings(ticker) for each ETF/Fund position
    → disaggregates into underlying sector/type buckets in charts
```

---

## Key concepts

### Domain model

```
Portfolio
  └── List[Position]
        ├── asset: Asset
        │     ├── ticker, name, asset_type, currency, sector
        │     └── constituents: List[Constituent]  ← legacy ETF look-through
        ├── quantity: float
        └── cost_basis: float  ← ALWAYS per share, never total
```

### Risk metrics

- **Volatility** — annualized std dev of daily returns × √252
- **Historical VaR (95%)** — 5th percentile of observed daily returns
- **Monte Carlo VaR (95%)** — parametric: 10,000 samples from N(mean, std), take percentile
- **Covariance matrix** — pairwise annualized covariances; useful for diversification analysis

---

## Data storage

All data lives under `data/` as Parquet files (gitignored):

```
data/
├── assets.parquet             — ticker, name, asset_type, currency, sector
├── portfolios.parquet         — name, created_at
├── positions.parquet          — portfolio_name, ticker, quantity, cost_basis (per share)
├── constituents.parquet       — parent_ticker, constituent_ticker, weight (legacy)
├── fund_holdings.parquet      — fund_ticker, as_of_date, holding_ticker, holding_name, weight, sector, asset_type
└── prices/
    └── {TICKER}.parquet       — date-indexed daily close prices
```

Inspect any file:

```python
import pandas as pd
pd.read_parquet("data/assets.parquet")
pd.read_parquet("data/fund_holdings.parquet")
pd.read_parquet("data/prices/AAPL.parquet").tail(10)
```

---

## Streamlit dashboard tabs

The dashboard has two views (sidebar radio: Single Portfolio / Multi-Portfolio Dashboard).

**Single Portfolio tabs:**

| Tab | Contents |
|-----|----------|
| Overview | Position table with P&L, allocation donut |
| Price History | Normalised prices, cumulative returns, daily returns |
| Exposure | Asset-type pie, sector bar — ETF/Fund positions disaggregated via fund_holdings if uploaded |
| Risk | Volatility, VaR, correlation heatmap, return distribution, covariance matrix |
| Positions | Editable position table, add new positions |
| Security Master | Edit asset metadata (name, type, sector, currency) |
| Trades | Record BUY/SELL trades, view trade history |
| Lookthrough | Upload ETF/fund holdings CSVs, view snapshots, sector breakdown, portfolio contribution table |

**Multi-Portfolio Dashboard:**
- Summary table across all portfolios (returns, vol, VaR, drawdown)
- Returns, risk, and drawdown comparison charts
- Wealth Projection with configurable growth assumptions

---

## Things to watch out for

- **`cost_basis` is per share**, not total. `Portfolio.total_cost()` = Σ (quantity × cost_basis). Storing total cost causes double-multiplication.
- **`Type` column must match AssetType enum exactly**: `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `Crypto` — not `stock`, `Equity`, etc.
- **`collect` before `report`/agent** — risk metrics need price data in the DB.
- **`portfolios.parquet` and `positions.parquet` must stay in sync** — writing one without the other leaves the portfolio invisible to `portfolio list`.
- **Adding a column to a parquet file requires deleting it first** — parquet has a fixed schema; old rows won't have new columns. Delete the file and re-run `load` to recreate cleanly.
- **Run from project root** — `data/` path is relative; running from `src/` creates a new empty store in the wrong place.
- **String columns with all-NaN values** — pandas infers dtype as `float64`, which breaks Streamlit's `TextColumn` config. The DB layer casts `name`, `sector`, `currency` to `str` on read via `get_all_assets()`. Do the same for any new string columns added to parquet files.

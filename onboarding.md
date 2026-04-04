# Onboarding Guide — invest_monitor

Welcome. This document will get you from zero to making changes in the codebase.

---

## What this project does

`invest_monitor` is a CLI tool for tracking an investment portfolio. You give it a CSV of your holdings, it fetches historical prices from Yahoo Finance, stores everything locally, and produces:

- **Exposure reports** — how much of your portfolio is in each asset type and sector
- **Risk metrics** — volatility, Value-at-Risk (historical and Monte Carlo), covariance matrix

---

## Setup

**Requirements:** Python 3.14+

```bash
# Clone and enter the project
cd invest_monitor

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

The data directory is created automatically at `data/` the first time you run any command. You don't need to set it up manually.

> **Note:** Always run CLI commands from the project root. The data path is relative, so running from a different directory will create a new empty data store in the wrong place.

---

## Running the tool

There are three CLI commands. Run them from the project root:

```bash
# 1. Load a portfolio from CSV into the database
python src/cli.py load portfolio.csv --name "My Portfolio"

# 2. Fetch historical price data for all assets in the database
python src/cli.py collect --period 1y

# 3. Generate exposure + risk report
python src/cli.py report portfolio.csv
```

Typical workflow: `load` → `collect` → `report`. After the initial load and collect, you only need to re-run `collect` to refresh prices and `report` to see updated metrics.

---

## Portfolio CSV format

The `load` and `report` commands expect a CSV with these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `Ticker` | Yes | Stock ticker (e.g. `AAPL`) |
| `Name` | Yes | Human-readable name |
| `Type` | Yes | One of: `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `Crypto` |
| `Quantity` | Yes | Number of units held |
| `CostBasis` | Yes | Price paid per unit |
| `Currency` | No | Defaults to `USD` |
| `Sector` | No | e.g. `Technology`, `Healthcare` |
| `ConstituentTickers` | No | Comma-separated tickers for ETF/Fund look-through |
| `ConstituentWeights` | No | Comma-separated weights matching `ConstituentTickers` |

**Example:**

```csv
Ticker,Name,Type,Quantity,CostBasis,Currency,Sector
AAPL,Apple Inc,Stock,10,150.00,USD,Technology
AGG,iShares Core US Aggregate Bond,ETF,5,100.00,USD,
```

**For an ETF with look-through:**

```csv
Ticker,Name,Type,Quantity,CostBasis,ConstituentTickers,ConstituentWeights
SPY,S&P 500 ETF,ETF,2,400.00,"AAPL,MSFT,AMZN","0.07,0.06,0.03"
```

---

## Codebase map

```
src/
├── cli.py           — Entry point. Three Click commands: load / collect / report
├── models.py        — Domain objects: Asset, Position, Portfolio, Constituent, AssetType
├── collector.py     — Fetches prices from Yahoo Finance (yfinance), saves to DB
├── reporting.py     — Calculates exposure and risk metrics from DB data
├── database/
│   └── database.py  — Parquet store. Reads/writes assets, constituents, and per-ticker price files
└── data/
    └── ingestion.py — Parses portfolio CSV into domain objects, saves assets to DB
```

---

## How the pieces connect

### Loading a portfolio (`cli load`)

```
cli.py:load()
  → Ingester.load_portfolio_from_csv()
      reads CSV row by row
      creates Asset + Constituent objects
      calls Database.add_asset() for each
      returns Portfolio with all Positions
```

### Collecting prices (`cli collect`)

```
cli.py:collect()
  → Collector.update_all_assets()
      queries all tickers from DB
      calls yfinance.download() in batches
      calls Database.save_prices() for each ticker
```

### Generating a report (`cli report`)

```
cli.py:report()
  → Ingester.load_portfolio_from_csv()   (re-reads CSV)
  → ReportingEngine.get_portfolio_exposure()
      aggregates positions by AssetType + Sector
      decomposes composite assets (ETFs/Funds) into constituents
  → ReportingEngine.get_portfolio_risk_metrics()
      Database.get_historical_prices()   (pivoted DataFrame)
      computes daily returns (pct_change)
      weights by quantity × cost_basis
      calculates volatility, historical VaR, Monte Carlo VaR, covariance
```

---

## Key concepts to know

### Domain model

```
Portfolio
  └── List[Position]
        ├── asset: Asset
        │     ├── ticker, name, asset_type, currency, sector
        │     └── constituents: List[Constituent]  ← only for ETFs/Funds
        ├── quantity: float
        └── cost_basis: float
```

`Asset.is_composite()` returns `True` if the asset has constituents. The reporting engine uses this to do look-through — instead of treating an ETF as one holding, it breaks it down into its underlying tickers.

### Risk metrics

- **Volatility** — annualized standard deviation of daily returns (multiplied by √252)
- **Historical VaR (95%)** — the 5th percentile of observed daily returns; "on the worst 5% of days, you lose at least this much"
- **Monte Carlo VaR (95%)** — same idea, but using 10,000 simulated days drawn from a normal distribution fitted to historical data
- **Covariance matrix** — pairwise annualized covariances between assets; useful for understanding diversification

---

## Data storage

All data lives under `data/` as Parquet files:

```
data/
├── assets.parquet             — one row per asset (ticker, name, asset_type, currency, sector)
├── constituents.parquet       — one row per constituent (parent_ticker, constituent_ticker, weight)
└── prices/
    ├── AAPL.parquet           — date-indexed price history for AAPL
    ├── MSFT.parquet
    └── ...
```

You can inspect any file with pandas:

```python
import pandas as pd
pd.read_parquet("data/assets.parquet")
pd.read_parquet("data/prices/AAPL.parquet").tail(10)
```

---

## Making a change — worked examples

### Add a new risk metric (e.g. Sharpe ratio)

1. Open `src/reporting.py`
2. Add a method to `ReportingEngine`:
   ```python
   def calculate_sharpe(self, returns: pd.DataFrame, risk_free_rate: float = 0.0) -> pd.Series:
       excess = returns.mean() - risk_free_rate / 252
       return (excess / returns.std()) * (252 ** 0.5)
   ```
3. Call it inside `get_portfolio_risk_metrics()` and add the result to the returned dict
4. Print it in `cli.py:report()` alongside the existing metrics

### Add a new column to the CSV (e.g. `Country`)

1. Add `country: Optional[str] = None` to the `Asset` dataclass in `src/models.py`
2. In `src/database/database.py`, add `"country": asset.country` to the `new_row` dict inside `add_asset()`
3. In `src/data/ingestion.py`, read `row.get('Country')` and pass it when constructing the `Asset`
4. Delete `data/assets.parquet` so it is recreated with the new column on next `load`

### Add a new CLI command

1. Open `src/cli.py`
2. Add a new function decorated with `@cli.command()` and `@click.argument` / `@click.option` as needed
3. Wire it to the appropriate service class (`ReportingEngine`, `Collector`, etc.)

---

## Things to watch out for

- **Run from the project root.** The data path is relative — running from `src/` will silently create a new empty `data/` in the wrong place.
- **`Type` column must match exactly.** Values like `"stock"` (lowercase) or `"Equity"` will fail; use `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `Crypto`.
- **`collect` before `report`.** The report reads prices from Parquet. If you haven't collected data, risk metrics will be empty or error.
- **Adding a column to `assets.parquet` requires deleting the file.** Parquet files have a fixed schema — if you add a field to `Asset` and re-run `load`, old rows won't have that column. Delete `data/assets.parquet` to let it be recreated cleanly.
- **Tests live in `tests/`.** Run with `PYTHONPATH=. .venv/bin/python -m pytest tests/ -v`.

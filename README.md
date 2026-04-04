# Invest Monitor

A personal investment portfolio monitoring tool with risk analytics, a Streamlit dashboard, and a Claude-powered risk management agent.

## Features

- **Portfolio tracking** — load and manage multiple portfolios stored as Parquet files
- **Price collection** — fetch historical pricing via yfinance
- **Risk analytics** — annualised volatility, historical and Monte Carlo VaR, covariance/correlation matrices, max drawdown
- **Exposure reporting** — breakdown by asset type and sector
- **Stress testing** — apply named historical scenarios (2008, COVID, dot-com, rate hikes, inflation) or custom shocks
- **Monte Carlo simulation** — forward simulation of portfolio value with percentile outcomes
- **Streamlit dashboard** — interactive UI with overview, price history, exposure, and risk tabs
- **AI agent** — conversational risk analyst powered by Claude Opus 4.6 with adaptive thinking

## Project Structure

```
invest_monitor/
├── src/
│   ├── models.py          # Data models: Asset, Position, Portfolio, AssetType
│   ├── database/
│   │   └── database.py    # Parquet-backed data store (assets, portfolios, positions, prices)
│   ├── data/
│   │   └── ingestion.py   # CSV ingestion into the database
│   ├── collector.py       # yfinance price fetcher
│   ├── reporting.py       # Risk and exposure calculations
│   ├── agent/
│   │   ├── agent.py       # RiskAgent: multi-turn Claude conversation loop
│   │   └── skills.py      # Tool-decorated risk skills exposed to the agent
│   ├── app.py             # Streamlit dashboard
│   └── cli.py             # Click CLI entry point
└── data/
    ├── securities.parquet # Security master (ticker, CUSIP, name, asset type, exchange)
    ├── assets.parquet     # Asset metadata used by the database layer
    ├── portfolios.parquet # Portfolio registry
    ├── positions.parquet  # Holdings (portfolio, ticker, quantity, cost basis)
    └── prices/            # Per-ticker historical price parquet files
```

## Setup

```bash
# Install dependencies
uv sync

# Or with pip
pip install -e .
```

Requires an `ANTHROPIC_API_KEY` environment variable to use the agent.

## CLI Usage

```bash
# Load a portfolio from CSV
invest-monitor load path/to/portfolio.csv --name "My Portfolio"

# Fetch historical prices (all assets or a specific portfolio)
invest-monitor collect --period 1y
invest-monitor collect --period 1y --portfolio "My Portfolio"

# Generate a risk and exposure report
invest-monitor report "My Portfolio"

# List and manage portfolios
invest-monitor portfolio list
invest-monitor portfolio delete "My Portfolio"

# Launch the AI risk agent (interactive)
invest-monitor agent
invest-monitor agent --portfolio "My Portfolio"
invest-monitor agent --query "Which portfolio has the highest VaR?"
```

## Streamlit Dashboard

```bash
streamlit run src/app.py
```

The dashboard provides four tabs:

| Tab | Contents |
|-----|----------|
| Overview | Position table with current prices, P&L, and asset-type allocation chart |
| Price History | Normalised price chart and daily returns bar chart |
| Exposure | Asset-type and sector breakdown (pie + bar charts) |
| Risk | Volatility, VaR, correlation heatmap, return distribution, covariance matrix |

## Portfolio CSV Format

When importing via the CLI or dashboard upload:

| Column | Required | Description |
|--------|----------|-------------|
| Ticker | Yes | Asset ticker symbol |
| Name | Yes | Human-readable name |
| Type | Yes | `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `Crypto` |
| Quantity | Yes | Number of units held |
| CostBasis | Yes | Cost basis per unit |
| Currency | No | Defaults to `USD` |
| Sector | No | Sector classification |

## Data Layer

All data is stored as Parquet files under `data/`:

- **`securities.parquet`** — security master with CUSIP, exchange, and asset type for all known instruments
- **`assets.parquet`** — asset metadata consumed by the database layer
- **`portfolios.parquet`** — portfolio registry with creation timestamps
- **`positions.parquet`** — flat holdings table: `portfolio_name`, `ticker`, `quantity`, `cost_basis`
- **`prices/<TICKER>.parquet`** — per-ticker daily closing prices indexed by date

## AI Agent Skills

The risk agent has access to the following tools:

| Skill | Description |
|-------|-------------|
| `list_portfolios` | List all portfolios in the database |
| `get_portfolio_summary` | Full position breakdown with weights |
| `get_risk_metrics` | Volatility, historical VaR, Monte Carlo VaR |
| `get_exposure_breakdown` | Exposure by asset type and sector |
| `check_concentration_risk` | Flag positions above a weight threshold |
| `get_correlation_matrix` | Pairwise correlations with high-correlation alerts |
| `calculate_max_drawdown` | Peak-to-trough drawdown per asset and portfolio |
| `get_price_performance` | Returns over 1M, 3M, 6M, and 1Y look-back periods |
| `get_cumulative_returns` | Total cumulative price return per asset from start of history (or a given date) |
| `list_stress_scenarios` | Show available named historical scenarios |
| `run_stress_test` | Apply a named scenario and estimate P&L impact |
| `apply_custom_shock` | Apply arbitrary shocks by ticker, sector, or asset type |
| `simulate_forward` | Monte Carlo forward simulation with percentile outcomes |

## Asset Types

| Value | Meaning |
|-------|---------|
| `Stock` | Individual equities and ADRs |
| `ETF` | Exchange-traded funds |
| `Bond` | Fixed income (treasuries, corporates) |
| `Fund` | Mutual funds |
| `Cash` | Cash, money market, CDs |
| `Crypto` | Cryptocurrencies |

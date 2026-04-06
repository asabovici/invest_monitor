# Invest Monitor

A personal investment portfolio monitoring tool with risk analytics, ETF lookthrough, a Streamlit dashboard, and three Claude-powered agents.

## Features

- **Portfolio tracking** — load and manage multiple portfolios stored as Parquet files
- **Price collection** — fetch historical pricing via yfinance
- **ETF / Fund lookthrough** — upload monthly holdings files from any vendor (iShares, Vanguard, etc.) to disaggregate ETF positions into underlying sector and asset-type exposure
- **Risk analytics** — annualised volatility, historical and Monte Carlo VaR, covariance/correlation matrices, max drawdown
- **Exposure reporting** — breakdown by asset type and sector, with automatic lookthrough for funds that have holdings uploaded
- **Stress testing** — apply named historical scenarios (2008, COVID, dot-com, rate hikes, inflation) or custom shocks
- **Monte Carlo simulation** — forward simulation of portfolio value with percentile outcomes
- **Streamlit dashboard** — interactive UI across eight tabs per portfolio plus a multi-portfolio dashboard
- **AI agents** — three conversational agents powered by Claude Opus 4.6: risk analyst, wealth planner, and research / capital deployment

## Project Structure

```
invest_monitor/
├── src/
│   ├── models.py          # Data models: Asset, Position, Portfolio, AssetType, Constituent
│   ├── database/
│   │   └── database.py    # Parquet-backed data store
│   ├── data/
│   │   └── ingestion.py   # Portfolio CSV + ETF holdings CSV parsers
│   ├── collector.py       # yfinance price fetcher
│   ├── reporting.py       # Risk and exposure calculations
│   ├── agent/
│   │   ├── agent.py           # RiskAgent
│   │   ├── skills.py          # Risk agent tools (13 skills)
│   │   ├── wealth_agent.py    # WealthAgent
│   │   ├── wealth_skills.py   # Wealth agent tools (9 skills)
│   │   ├── research_agent.py  # ResearchAgent
│   │   └── research_skills.py # Research tools + server-side web search
│   ├── app.py             # Streamlit dashboard
│   └── cli.py             # Click CLI entry point
└── data/                  # gitignored
    ├── assets.parquet
    ├── portfolios.parquet
    ├── positions.parquet
    ├── constituents.parquet
    ├── fund_holdings.parquet
    └── prices/
```

## Setup

```bash
# Install dependencies
uv sync

# Or with pip
pip install -e .
```

Requires an `ANTHROPIC_API_KEY` environment variable to use any agent.

## CLI Usage

```bash
# Load a portfolio from CSV
invest-monitor load path/to/portfolio.csv --name "My Portfolio"

# Fetch historical prices
invest-monitor collect --period 1y
invest-monitor collect --period 1y --portfolio "My Portfolio"

# Generate a risk and exposure report
invest-monitor report "My Portfolio"

# List and manage portfolios
invest-monitor portfolio list
invest-monitor portfolio delete "My Portfolio"

# Launch agents (interactive or one-shot)
invest-monitor agent --portfolio "My Portfolio"
invest-monitor agent --query "Which portfolio has the highest VaR?"
invest-monitor wealth --portfolio "My Portfolio"
invest-monitor research --portfolio "My Portfolio" --query "Deploy $100k without increasing tech exposure"
```

## Streamlit Dashboard

```bash
streamlit run src/app.py
```

Two views selectable from the sidebar:

**Single Portfolio** (eight tabs):

| Tab | Contents |
|-----|----------|
| Overview | Position table with current prices, P&L, and allocation donut |
| Price History | Normalised price chart, cumulative returns, daily returns |
| Exposure | Asset-type pie + sector bar; ETF/Fund positions disaggregated via uploaded holdings |
| Risk | Volatility, VaR, correlation heatmap, return distribution, covariance matrix |
| Positions | Editable position table; add new positions |
| Security Master | Edit asset metadata (name, type, sector, currency) |
| Trades | Record BUY/SELL trades; view trade history |
| Lookthrough | Upload ETF/fund holdings CSVs, view snapshots, sector breakdown, portfolio contribution |

**Multi-Portfolio Dashboard:**
- Summary table across all portfolios (1M/3M/6M/1Y returns, vol, VaR, drawdown)
- Returns, risk, and drawdown comparison charts
- Wealth Projection with configurable growth assumptions per asset class

## Portfolio CSV Format

| Column | Required | Description |
|--------|----------|-------------|
| Ticker | Yes | Asset ticker symbol |
| Name | Yes | Human-readable name |
| Type | Yes | `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `Crypto` |
| Quantity | Yes | Number of units held |
| CostBasis | Yes | Cost basis **per share** (not total) |
| Currency | No | Defaults to `USD` |
| Sector | No | Sector classification |

## ETF / Fund Lookthrough

Upload a monthly holdings file from your ETF vendor in the **Lookthrough** tab. The parser auto-detects common formats including iShares and Vanguard (handles metadata header rows). It fuzzy-matches columns for ticker, name, weight, sector, and asset class.

Once uploaded, the **Exposure** tab automatically disaggregates that ETF/Fund position into its underlying sectors and asset types across all charts and tables.

**Supported weight formats:** `7.0` (percent) and `0.07` (fraction) are both handled — the parser detects which by checking whether the column sums to > 1.5.

## Data Layer

All data stored as Parquet files under `data/` (gitignored):

| File | Description |
|------|-------------|
| `assets.parquet` | Asset metadata: ticker, name, asset_type, currency, sector |
| `portfolios.parquet` | Portfolio registry with creation timestamps |
| `positions.parquet` | Holdings: portfolio_name, ticker, quantity, cost_basis (per share) |
| `constituents.parquet` | Legacy inline ETF look-through: parent_ticker, constituent_ticker, weight |
| `fund_holdings.parquet` | Monthly ETF/fund holdings snapshots: fund_ticker, as_of_date, holding_ticker, holding_name, weight, sector, asset_type |
| `prices/<TICKER>.parquet` | Per-ticker daily closing prices indexed by date |

## AI Agent Skills

See [AGENTS.md](AGENTS.md) for the full skill reference across all three agents.

## Asset Types

| Value | Meaning |
|-------|---------|
| `Stock` | Individual equities and ADRs |
| `ETF` | Exchange-traded funds |
| `Bond` | Fixed income (treasuries, corporates) |
| `Fund` | Mutual funds |
| `Cash` | Cash, money market, CDs |
| `Crypto` | Cryptocurrencies |

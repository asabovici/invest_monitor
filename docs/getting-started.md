# Getting Started

## Requirements

Python 3.14 or later. Linux / macOS / Windows all work.

## Install

```bash
git clone <repo-url> invest_monitor
cd invest_monitor

# Preferred — uv handles the venv automatically
uv sync

# Or with pip
pip install -e .
```

The data directory is created automatically at `data/` the first time you run any command. You don't need to set it up manually.

!!! warning "Run from project root"
    The data path is relative, so always run CLI commands and `streamlit run` from the project root. Otherwise a fresh, empty `data/` will be created wherever you launched from.

## Anthropic API key

The three Claude-powered agents (Risk, Wealth, Research) need `ANTHROPIC_API_KEY`. The simplest setup is a project-local `.env` file:

=== "Project-local `.env` (recommended)"

    ```bash
    cp .env.example .env
    # Edit .env, paste your key from https://console.anthropic.com → Settings → API Keys
    ```

    `src/env.py` loads this at module import time via `python-dotenv`. `.env` is gitignored.

=== "Shell export"

    ```bash
    export ANTHROPIC_API_KEY=sk-ant-...
    ```

!!! danger "Restart Streamlit after editing .env"
    `load_dotenv()` runs once at module import time and Python caches imports across `st.rerun()`. A browser refresh is **not** enough — fully stop and re-launch `streamlit run src/app.py` after editing `.env`.

## Your first portfolio

Three ways to create one:

=== "Upload CSV via the dashboard"

    1. Launch the dashboard: `streamlit run src/app.py`
    2. Open the sidebar's **Import from CSV** expander.
    3. Pick a CSV with columns `Ticker`, `Name`, `Type`, `Quantity`, `CostBasis` (+ optional `Currency`, `Sector`).
    4. Click **Import** — done.

=== "Empty portfolio + Trade Blotter"

    Useful if you want to build up history via actual trades:

    1. In the sidebar's **New Empty Portfolio** expander, name it and click **Create**.
    2. Go to the **📋 Trades** tab and record BUY/SELL trades — they replay into positions.

=== "From CSV via CLI"

    ```bash
    invest-monitor load path/to/portfolio.csv --name "My Portfolio"
    invest-monitor portfolio list
    ```

### CSV format

| Column | Required | Description |
|--------|----------|-------------|
| `Ticker` | Yes | Asset ticker symbol |
| `Name` | Yes | Human-readable name |
| `Type` | Yes | `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `CD`, `Crypto` |
| `Quantity` | Yes | Number of units held |
| `CostBasis` | Yes | Cost **per share** (not total) |
| `Currency` | No | Defaults to `USD` |
| `Sector` | No | e.g. `Technology`, `Healthcare` |

`Income Rate` and `Payment Frequency` aren't read from CSV — they default to 0 / 1. Set them later in the **🏢 Security Master** tab.

## Collect prices

Most analytics depend on price data:

```bash
invest-monitor collect --period 1y
# Or scoped to one portfolio:
invest-monitor collect --period 1y --portfolio "My Portfolio"
```

Or use the sidebar **Collect Prices** button once you've opened a portfolio.

## Compute daily metrics

The Performance Attribution and Benchmarks features read from precomputed daily-metric parquet files. After collecting prices:

```bash
invest-monitor metrics refresh        # incremental, only re-walks last 30 days
invest-monitor metrics refresh --full # recompute everything from scratch
```

Or click **Refresh metrics** in the sidebar (always visible).

## Demo mode

To play with the app without exposing live data, flip **🎭 Demo mode** at the top of the sidebar. It switches every read to a separate `data_demo/` directory and auto-seeds a sample portfolio set on first activation. Your live `data/` is never touched. From the CLI:

```bash
invest-monitor demo seed         # idempotent
invest-monitor demo seed --reset # wipe & reseed
invest-monitor demo reset        # delete data_demo/
```

## Typical workflow

```
load (or empty + trades)
   ↓
collect    # fetch prices
   ↓
metrics refresh   # build daily metrics
   ↓
open dashboard / run agents
```

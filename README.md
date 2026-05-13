# Invest Monitor

A personal investment portfolio monitoring tool with risk analytics, ETF lookthrough, daily performance attribution, a Streamlit dashboard, and three Claude-powered agents.

## Features

- **Portfolio tracking** — load and manage multiple portfolios stored as Parquet files; create empty portfolios from the UI or CLI and build them up via the Trade Blotter
- **Price collection** — fetch historical pricing via yfinance
- **ETF / Fund lookthrough** — upload monthly holdings files from any vendor (iShares, Vanguard, etc.) **or** fetch a yfinance fund profile (asset-class + sector-weighting breakdown) with one click to disaggregate ETF positions into underlying sector and asset-type exposure
- **Risk analytics** — annualised volatility, historical and Monte Carlo VaR, covariance/correlation matrices, max drawdown
- **Exposure reporting** — breakdown by asset type and sector, with automatic lookthrough for funds that have holdings or fund-profile data
- **Sector stress testing** — apply named historical scenarios (2008, dot-com, rate hike, energy shock, etc.), edit shocks freely, or use **implied (beta-driven) shocks**: pick a driver sector + shock %, and every other sector's response is derived from a 20-year pairwise OLS beta matrix computed from SPDR sector ETFs
- **Income projection** — annual cash flow from coupons (Bond/CD), interest (Cash), and dividends (Stock/ETF/Fund), with a payment-frequency-aware 12-month schedule
- **Performance attribution** — daily security-, portfolio-, and contribution-level metrics persisted to Parquet; cumulative-return + drawdown charts, top contributors/detractors per period, and stacked contribution by asset type over time. **Trade replay (v2)** reconstructs historical positions from the BUY/SELL ledger when trades are recorded; portfolios without trades fall back to a static-current-positions view.
- **Wealth projection** — deterministic multi-period growth **or** Monte Carlo with cross-asset correlation matrix and historical-regime presets (1970s Stagflation, 1980s Bull Run, 1990s Japan Deflation, 2000s Dual Shock, 2010s Recovery, 2020s Rate-Hike Era)
- **Demo mode** — sidebar toggle (or CLI) that switches to a separate `data_demo/` dataset with sample portfolios, so you can screenshot/share without exposing live accounts
- **Analytics & return production** — scheduled jobs that keep prices, attribution metrics, sector betas, and fund profiles fresh. Run on demand from the dashboard's **⚙️ Production** view, or wire `invest-monitor production run` into cron / systemd for true automation. Run log + an **Issues** tab surfaces any failures.
- **Streamlit dashboard** — interactive UI across nine tabs per portfolio plus a multi-portfolio dashboard with embedded **agent chat**
- **AI agents** — three conversational agents powered by Claude (Risk Analyst, Wealth Planner, Research / Capital Deployment), reachable from the CLI **or directly from the dashboard sidebar tabs**

## Project Structure

```
invest_monitor/
├── .env / .env.example    # ANTHROPIC_API_KEY (loaded by src/env.py)
├── src/
│   ├── env.py             # Loads .env into os.environ at import time
│   ├── models.py          # Data models: Asset, Position, Portfolio, AssetType, Constituent
│   ├── scenarios.py       # Named MC scenarios, cross-asset betas, sector stress presets,
│   │                      #   sector-ETF ticker map, regime presets (1970s … 2020s)
│   ├── database/
│   │   └── database.py    # Parquet-backed data store + schema auto-migration
│   ├── data/
│   │   └── ingestion.py   # Portfolio CSV + ETF holdings CSV parsers
│   ├── collector.py       # yfinance: prices, fund profiles, sector-ETF betas
│   ├── reporting.py       # Risk, exposure, income, sector stress
│   ├── attribution.py     # Daily security / portfolio / attribution metrics → parquet
│   ├── production.py      # Scheduled-job runner (JobRunner + JOB_REGISTRY)
│   ├── demo.py            # Seed/reset demo dataset (data_demo/)
│   ├── agent/
│   │   ├── agent.py           # RiskAgent
│   │   ├── skills.py          # Risk agent tools (13 skills)
│   │   ├── wealth_agent.py    # WealthAgent
│   │   ├── wealth_skills.py   # Wealth agent tools (11 skills)
│   │   ├── research_agent.py  # ResearchAgent
│   │   └── research_skills.py # Research tools + server-side web search
│   ├── app.py             # Streamlit dashboard
│   └── cli.py             # Click CLI entry point
├── data/                  # gitignored — live dataset
└── data_demo/             # gitignored — demo dataset (separate from live)
    ├── assets.parquet                  # ticker, name, asset_type, currency, sector,
    │                                     #   income_rate, payment_frequency
    ├── portfolios.parquet              # name, created_at
    ├── positions.parquet               # portfolio_name, ticker, quantity, cost_basis
    ├── constituents.parquet            # legacy inline ETF look-through
    ├── trades.parquet                  # ledger of BUY / SELL trades
    ├── fund_holdings.parquet           # vendor-uploaded ETF/fund holdings
    ├── fund_profiles.parquet           # yfinance asset_classes + sector_weightings
    ├── sector_betas.parquet            # pairwise sector betas from SPDR ETFs
    ├── daily_security_metrics.parquet  # per-ticker daily return / vol time series
    ├── daily_portfolio_metrics.parquet # per-portfolio daily value / return / drawdown
    ├── daily_attribution.parquet       # per (date, portfolio, ticker) contribution
    ├── production_jobs.parquet         # scheduled-job config + last-run status
    ├── production_runs.parquet         # append-only production run log
    └── prices/{TICKER}.parquet         # daily close prices
```

## Setup

```bash
# Install dependencies
uv sync

# Or with pip
pip install -e .
```

### Anthropic API key (for the agents)

Two ways to provide `ANTHROPIC_API_KEY`:

```bash
# 1. Project-local .env (recommended) — auto-loaded by src/env.py
cp .env.example .env
# Then edit .env and paste your key from https://console.anthropic.com → Settings → API Keys

# 2. Or export it in your shell
export ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored. **Restart Streamlit / the CLI process after changing `.env`** — `load_dotenv()` runs at module import time and Streamlit's hot-reload doesn't re-execute module-level imports, so a fresh process is required.

## CLI Usage

```bash
# ── Portfolios ─────────────────────────────────────────────────────────────
invest-monitor load path/to/portfolio.csv --name "My Portfolio"
invest-monitor portfolio list
invest-monitor portfolio create "Crypto"            # empty portfolio; add trades later
invest-monitor portfolio delete "My Portfolio"

# ── Prices ─────────────────────────────────────────────────────────────────
invest-monitor collect --period 1y
invest-monitor collect --period 1y --portfolio "My Portfolio"

# ── Reports ────────────────────────────────────────────────────────────────
invest-monitor report "My Portfolio"

# ── Daily metrics / attribution (persisted to parquet) ─────────────────────
invest-monitor metrics refresh                         # incremental (last 30d)
invest-monitor metrics refresh --portfolio "My Portfolio"
invest-monitor metrics refresh --from 2024-01-01       # from a date
invest-monitor metrics refresh --full                  # recompute entire history

# ── Production: scheduled analytics jobs ───────────────────────────────────
invest-monitor production status                       # job table + due flag
invest-monitor production run                          # run only what's due (cron-friendly)
invest-monitor production run-now refresh_attribution  # force-run one job
invest-monitor production daemon --check-every 60      # long-running loop

# ── Demo dataset (separate data_demo/ store; live data untouched) ──────────
invest-monitor demo seed                               # idempotent
invest-monitor demo seed --reset                       # wipe & reseed
invest-monitor demo reset                              # delete data_demo/

# ── Agents (interactive or one-shot) ───────────────────────────────────────
invest-monitor agent --portfolio "My Portfolio"
invest-monitor agent --query "Which portfolio has the highest VaR?"
invest-monitor wealth --portfolio "My Portfolio"
invest-monitor research --portfolio "My Portfolio" --query "Deploy $100k without increasing tech exposure"
```

## Streamlit Dashboard

```bash
streamlit run src/app.py
```

The sidebar has:
- 🎭 **Demo mode** toggle — flips every read to `data_demo/`; seeds the demo dataset on first activation. Live data untouched.
- View selector: **Multi-Portfolio Dashboard** / **Single Portfolio** / **⚙️ Production**.
- Portfolio selector, **New Empty Portfolio** expander, **Import from CSV** expander.
- **Refresh metrics** button — always visible; recomputes daily returns/risk/attribution for every portfolio and reports which used v2 trade replay vs v1 static current.
- **Collect Prices** button (appears once a portfolio is active) — fetches historical prices for the chosen period.

**Single Portfolio** (nine tabs):

| Tab | Contents |
|-----|----------|
| 📊 Overview | Position table with current prices, P&L, and allocation donut |
| 📈 Price History | Normalised price chart, cumulative returns, daily returns |
| 🥧 Exposure | Asset-type pie + sector bar; ETF/Fund positions disaggregated via uploaded holdings or yfinance fund profile |
| ⚠️ Risk | Volatility, VaR, correlation heatmap, return distribution, covariance heatmap, **Sector Stress Test** (Custom / Implied-from-driver-sector / 7 named scenarios), per-position stress P&L table + chart |
| 💵 Income | Annual income KPI, asset-type donut, payment-frequency-aware 12-month schedule, per-position detail |
| ✏️ Positions | Editable position table; add new positions |
| 🏢 Security Master | Edit asset metadata (name, type, sector, currency, **Income Rate**, **Payment Frequency**) |
| 📋 Trades | Record BUY/SELL trades; view trade history |
| 🔍 Lookthrough | Upload vendor holdings CSV, **or** fetch yfinance fund profile (asset_classes + sector_weightings) with one click |

**Multi-Portfolio Dashboard** (top to bottom):
- KPI strip (Portfolios, Positions, Total Cost, Current Value, Unrealised P&L)
- **Summary** table (1M/3M/6M/1Y returns, vol, VaR, drawdown) with merged-TOTAL row computed from a synthetic combined portfolio
- Cumulative-return, risk, and drawdown comparison charts
- **Income Projection** — annual / monthly / yield KPIs, per-portfolio table, donut by asset type, monthly payment schedule, per-position detail
- **Performance Attribution** — period selector (1M / 3M / 6M / 1Y / YTD / All), cumulative return + drawdown charts, end-of-period KPIs, top 10 contributors / detractors, stacked area of cumulative contribution by asset type. Each portfolio uses **v2 trade replay** (positions reconstructed from `trades.parquet` by cumulative-summing BUYs and SELLs) when trades are recorded, else **v1 static current positions**. Click **Refresh metrics** in the sidebar to (re)populate
- **Wealth Projection** — choose **Deterministic** (1–3 growth periods) or **Monte Carlo** (μ, σ per asset type, cross-asset correlation matrix, optional historical regime preset, fan chart with P10–P90 / P25–P75 bands, percentile table, per-portfolio outcome table, optional goal-probability KPI)
- **🤖 Ask the Agents** — embedded chat panel with three tabs (Risk / Wealth / Research); each agent is lazily instantiated and keeps its own history, scoped per mode (live vs demo)

**⚙️ Production view** (new top-level view for scheduling & monitoring analytics jobs):
- KPI strip: Jobs / Failed (last) / Due now.
- Red banner the moment any job fails its last run.
- **Run all due now** primary button — executes every job whose interval has elapsed.
- One row per job (bordered container) with: name + description, interval, last run, status icon, **Enabled** toggle, and a per-job **Run** button. The last error message renders inline when present.
- Two log tabs: **📜 Recent Runs** (full chronological feed, last 200) and **🚨 Issues** (filtered to `status=error`).

## Portfolio CSV Format

| Column | Required | Description |
|--------|----------|-------------|
| Ticker | Yes | Asset ticker symbol |
| Name | Yes | Human-readable name |
| Type | Yes | `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `CD`, `Crypto` |
| Quantity | Yes | Number of units held |
| CostBasis | Yes | Cost basis **per share** (not total) |
| Currency | No | Defaults to `USD` |
| Sector | No | Sector classification |

`Income Rate` and `Payment Frequency` aren't read from CSV — they default to 0 / 1 and you set them later in the **Security Master** tab. See [Income Rate semantics](#income-rate-semantics) below.

## ETF / Fund Lookthrough

Upload a monthly holdings file from your ETF vendor in the **Lookthrough** tab. The parser auto-detects common formats including iShares and Vanguard (handles metadata header rows). It fuzzy-matches columns for ticker, name, weight, sector, and asset class.

Once uploaded, the **Exposure** tab automatically disaggregates that ETF/Fund position into its underlying sectors and asset types across all charts and tables.

**Supported weight formats:** `7.0` (percent) and `0.07` (fraction) are both handled — the parser detects which by checking whether the column sums to > 1.5.

## Data Layer

All data stored as Parquet files under `data/` (gitignored). Demo data lives in `data_demo/` with the same schema. Schema auto-migrates on every `Database(...)` init — missing columns are backfilled with safe defaults.

| File | Description |
|------|-------------|
| `assets.parquet` | Asset metadata: ticker, name, asset_type, currency, sector, **income_rate**, **payment_frequency** |
| `portfolios.parquet` | Portfolio registry with creation timestamps |
| `positions.parquet` | Holdings: portfolio_name, ticker, quantity, cost_basis (per share) |
| `constituents.parquet` | Legacy inline ETF look-through: parent_ticker, constituent_ticker, weight |
| `trades.parquet` | Ledger of recorded BUY / SELL trades |
| `fund_holdings.parquet` | Vendor-uploaded ETF/fund holdings snapshots: fund_ticker, as_of_date, holding_ticker, holding_name, weight, sector, asset_type |
| `fund_profiles.parquet` | yfinance fund profile (long format): fund_ticker, as_of_date, category (`asset_class` \| `sector`), key, weight |
| `sector_betas.parquet` | Pairwise sector betas from SPDR sector ETFs: sector_a, sector_b, beta, as_of_date |
| `daily_security_metrics.parquet` | Per-ticker time series: date, ticker, price, daily_return, cum_return, rolling_vol_21d |
| `daily_portfolio_metrics.parquet` | Per-portfolio time series: date, portfolio_name, total_value, daily_return, cum_return, rolling_vol_21d, drawdown, max_drawdown |
| `daily_attribution.parquet` | Brinson decomposition: date, portfolio_name, ticker, weight, position_return, contribution_to_return, asset_type, sector |
| `production_jobs.parquet` | Scheduled-job config + last-run state: job_name, enabled, interval_minutes, last_run_at, last_status, last_error, last_duration_seconds |
| `production_runs.parquet` | Append-only run log: run_id, job_name, started_at, ended_at, status, error_message, details, duration_seconds |
| `prices/<TICKER>.parquet` | Per-ticker daily closing prices indexed by date |

The `daily_*.parquet` files are populated by the **Refresh metrics** button (or `invest-monitor metrics refresh`). Refresh is incremental by default — only dates newer than the latest stored date (plus a 30-day re-walk for safety against late price corrections) are recomputed. Use `--full` to recompute the entire history.

### Attribution reconstruction modes

`AttributionEngine.refresh_all()` chooses one of two modes per portfolio:

| Mode | When it's used | What it computes |
|---|---|---|
| **v2 — trade replay** | `trades.parquet` has any rows for the portfolio | Pivots trades into a `(date × ticker)` delta matrix (BUY +, SELL −), reindexes to the price calendar (off-calendar trades snap to the next trading day), `cumsum` to get running positions, multiplies by daily prices for `(date, ticker)` values. Each historical date uses the *actual* holdings on that date. Position quantities before the first trade are 0. |
| **v1 — static current** | No trades recorded for the portfolio (e.g. CSV-imported, never used the Trade Blotter) | Uses today's positions across the whole price history — answers "if I had held this portfolio over time …". |

Auto-routing is per-portfolio: a brokerage portfolio with full trade history gets v2, an old CSV-imported one in the same database gets v1. The Refresh-metrics success message lists which mode each portfolio used. The dashboard caption under **Performance Attribution** also documents the active behavior.

To upgrade a v1 portfolio to v2: record its historical trades in the **📋 Trades** tab (or via the future trade-import CSV), then click **Refresh metrics**. Until you do, the v1 view is shown.

## Production scheduling

The **⚙️ Production** view (and `invest-monitor production` CLI group) wraps the periodic refreshes the dashboard depends on. Each job's last status and full run history is persisted to `production_jobs.parquet` / `production_runs.parquet`, so failures don't disappear silently.

### Built-in jobs

| Job | Default interval | What it does |
|---|---|---|
| `collect_prices` | 24 h | `Collector.update_all_assets(period="1mo")` — appends trailing-month prices for every asset in the security master. |
| `refresh_attribution` | 24 h | `AttributionEngine.refresh_all()` — incremental refresh of `daily_*.parquet` (uses v2 trade replay where available). |
| `refresh_sector_betas` | 7 d | 20-year SPDR sector ETF fetch + `save_sector_betas` — keeps the implied-shock matrix current. |
| `refresh_fund_profiles` | 7 d | For every held ETF/Fund: `Collector.fetch_fund_profile` → `save_fund_profile`. |

Each job runs inside a try/except. Exceptions are captured into `production_runs.error_message` + a 4-frame traceback in `details`, and the job's `last_status` flips to `error` so it lights up in the dashboard's **🚨 Issues** tab.

### How to wire automation

The CLI's `production run` only executes jobs whose interval has elapsed since their last successful run — it's safe to call frequently, and nothing happens when nothing's due.

**Cron**:

```cron
*/15 * * * * cd /path/to/invest_monitor && /usr/bin/uv run invest-monitor production run >> ~/.invest-monitor-cron.log 2>&1
```

**systemd user service** (`~/.config/systemd/user/invest-monitor.service` + a `.timer`), **or** the foreground daemon:

```bash
nohup invest-monitor production daemon --check-every 60 > ~/.invest-monitor-daemon.log 2>&1 &
```

### Manual control from the dashboard

The Production view also lets you:
- toggle individual jobs on/off,
- click **Run** on a row to force-execute one job (ignores schedule and enabled flag),
- click **Run all due now** to fire every overdue job in one go,
- inspect run history and errors in the bottom tabs.

The Production state files live alongside the rest of the data, so live and demo modes each have their own independent schedule and run log.

## AI Agent Skills

See [AGENTS.md](AGENTS.md) for the full skill reference across all three agents.

## Asset Types

| Value | Meaning |
|-------|---------|
| `Stock` | Individual equities and ADRs |
| `ETF` | Exchange-traded funds |
| `Bond` | Fixed income (treasuries, corporates) |
| `Fund` | Mutual funds |
| `Cash` | Cash, money market |
| `CD` | Certificates of deposit (held at par; treated like Cash for pricing) |
| `Crypto` | Cryptocurrencies |

`Cash` and `CD` tickers don't need price files — the database synthesizes a 1-year constant-1.0 daily series for them automatically so risk metrics still compute (with vol = 0, drawdown = 0, etc.).

## Income Rate semantics

`income_rate` and `payment_frequency` on each asset capture recurring cash flows. **Units of `income_rate` depend on `asset_type`:**

| Asset type | `income_rate` unit | Annual income |
|---|---|---|
| Stock / ETF / Fund | **$ per share per payment** | `quantity × income_rate × payment_frequency` |
| Bond / CD | annual **%** (coupon) | `base_value × income_rate / 100` |
| Cash | annual **%** (yield) | `base_value × income_rate / 100` |

**Example.** BLK paying a $5.72 quarterly dividend → set `income_rate = 5.72`, `payment_frequency = 4`. The 12-month payment schedule chart in the Income tab respects `payment_frequency` (e.g. a monthly bond shows 12 payments, a semi-annual bond shows 2). Income contributions also lift each ticker's daily return inside `compute_portfolio_metrics`, so 1M/3M/6M/1Y horizon returns include yield.

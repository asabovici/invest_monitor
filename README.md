# Invest Monitor

A personal investment portfolio monitoring tool with risk analytics, ETF lookthrough, daily performance attribution, a Streamlit dashboard, and three Claude-powered agents.

## Features

- **Portfolio tracking** — load and manage multiple portfolios stored as Parquet files; create empty portfolios from the UI or CLI and build them up via the Trade Blotter
- **Price collection** — fetch historical pricing via yfinance
- **ETF / Fund lookthrough** — upload monthly holdings files from any vendor (iShares, Vanguard, etc.) **or** fetch a yfinance fund profile (asset-class + sector-weighting breakdown) with one click. A **🔍 Apply ETF / Fund lookthrough** toggle in the Overview tab, Exposure tab, and Multi-Portfolio Dashboard's Aggregate Exposure section replaces opaque ETF buckets with their underlying constituents — vendor holdings give you ticker-level detail, yfinance falls back to sector-level when no vendor CSV is loaded
- **Risk analytics** — annualised volatility, historical and Monte Carlo VaR, covariance/correlation matrices, max drawdown
- **Exposure reporting** — breakdown by asset type and sector, with automatic lookthrough for funds that have holdings or fund-profile data
- **Sector stress testing** — apply named historical scenarios (2008, dot-com, rate hike, energy shock, etc.), edit shocks freely, or use **implied (beta-driven) shocks**: pick a driver sector + shock %, and every other sector's response is derived from a 20-year pairwise OLS beta matrix computed from SPDR sector ETFs
- **Income projection** — annual cash flow from coupons (Bond/CD), interest (Cash), and dividends (Stock/ETF/Fund), with a payment-frequency-aware 12-month schedule
- **Performance attribution** — daily security-, portfolio-, and contribution-level metrics persisted to Parquet; cumulative-return + drawdown charts, top contributors/detractors per period, and stacked contribution by asset type over time. **Trade replay (v2)** reconstructs historical positions from the BUY/SELL ledger when trades are recorded; portfolios without trades fall back to a static-current-positions view.
- **Wealth projection** — deterministic multi-period growth **or** Monte Carlo with cross-asset correlation matrix and historical-regime presets (1970s Stagflation, 1980s Bull Run, 1990s Japan Deflation, 2000s Dual Shock, 2010s Recovery, 2020s Rate-Hike Era). Optional **Safe Withdrawal Rate** layer (Bengen-style, with inflation adjustment) — toggle on, set a primary SWR%, and in MC mode compare survival across multiple rates against the same return paths to find the highest SWR that meets your survival threshold.
- **Benchmark portfolios** — eight built-in named recipes (60/40, All Seasons / Dalio, Golden Butterfly, Permanent Portfolio / Browne, Risk Parity, 3-Fund Bogle, Coffeehouse / Schultheis, Larry Portfolio / Swedroe) constructed from public ETF proxies. Overlay on the Performance Attribution cumulative-return chart and get an apples-to-apples delta vs each portfolio over the selected window
- **Portfolio groups** — many-to-many tagging (e.g. *Taxable*, *Tax-Free*, *Retirement*). Filter the Multi-Portfolio Dashboard to a group, or flip **"View as combined portfolio"** to merge the group's member portfolios into a single synthetic entity (quantity-summed, weighted-average cost basis) for benchmark comparison and projection
- **Demo mode** — sidebar toggle (or CLI) that switches to a separate `data_demo/` dataset with sample portfolios, so you can screenshot/share without exposing live accounts
- **Analytics & return production** — scheduled jobs that keep prices, attribution metrics, sector betas, and fund profiles fresh. Run on demand from the dashboard's **⚙️ Production** view, or wire `invest-monitor production run` into cron / systemd for true automation. Run log + an **Issues** tab surfaces any failures.
- **Streamlit dashboard** — interactive UI across nine tabs per portfolio plus a multi-portfolio dashboard with embedded **agent chat**
- **AI agents** — five conversational agents powered by Claude: Risk, Wealth, Research, Portfolio Manager, and CIO. PM builds defensible trade proposals (BUY/SELL orders with dollar amounts and share counts, sector-tilt projections); CIO reviews them and produces a structured approve / override / more-research decision. All reachable from the CLI **or directly from the dashboard tabs**. Conversations can be summarised (via Haiku) and stored in `agent_summaries.json`, then loaded as priming context into future chats — even across different agents. **Wealth, PM, and CIO can also export markdown reports** via an `export_report` skill — files land in `<data_dir>/reports/`, scoped to the active dataset
- **Multi-agent coordination graph** — a LangGraph pipeline (Researcher → Portfolio Manager → Risk Manager → CIO) sharing a single `TradingState`, with a bounded PM ↔ Risk revision loop, `MemorySaver` checkpointing, and an optional human-in-the-loop pause before the CIO signs off. Currently runs end-to-end on deterministic stub nodes; the PM and CIO conversational agents are the human-facing counterparts. See [`docs/multi-agent-graph.md`](docs/multi-agent-graph.md)

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
│   ├── scheduler.py       # systemd --user timer install / uninstall / status
│   ├── benchmarks.py      # Named benchmark portfolios (60/40, All Seasons, ...)
│   ├── agent_summaries.py # Save + load summaries of past agent conversations
│   ├── demo.py            # Seed/reset demo dataset (data_demo/)
│   ├── agent/
│   │   ├── agent.py                  # RiskAgent
│   │   ├── skills.py                 # Risk agent tools (13 skills)
│   │   ├── wealth_agent.py           # WealthAgent
│   │   ├── wealth_skills.py          # Wealth agent tools (11 skills)
│   │   ├── research_agent.py         # ResearchAgent
│   │   ├── research_skills.py        # Research tools + server-side web search
│   │   ├── portfolio_manager_agent.py # PortfolioManagerAgent
│   │   ├── pm_skills.py              # PM tools (6 skills: snapshot, propose_trades, …)
│   │   ├── cio_agent.py              # CIOAgent
│   │   └── cio_skills.py             # CIO tools (6 skills: holistic_view, review, approve, …)
│   ├── trading_graph/         # LangGraph multi-agent coordination
│   │   ├── state.py           # TradingState + reducers
│   │   ├── config.py          # Settings (HITL, max_revisions, risk thresholds)
│   │   ├── routing.py         # Conditional-edge functions
│   │   ├── graph.py           # build_graph() — StateGraph + MemorySaver
│   │   ├── run.py             # CLI smoke entrypoint
│   │   └── nodes/             # researcher, portfolio_manager, risk_manager, cio
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
    ├── groups.parquet                  # portfolio group registry
    ├── portfolio_groups.parquet        # many-to-many group ↔ portfolio
    ├── agent_summaries.json            # saved summaries of past agent chats
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

# ── systemd user timers (Linux) ────────────────────────────────────────────
invest-monitor production schedule list                # timer status per job
invest-monitor production schedule install refresh_attribution
invest-monitor production schedule install collect_prices --interval 720  # override (min)
invest-monitor production schedule uninstall refresh_attribution

# ── Agent conversation summaries ───────────────────────────────────────────
invest-monitor summaries list                              # newest first
invest-monitor summaries list --agent risk
invest-monitor summaries show "risk__2026-05-17T14:30:00"
invest-monitor summaries delete "risk__2026-05-17T14:30:00"

# ── Portfolio groups (Taxable, Tax-Free, Retirement, ...) ─────────────────
invest-monitor group list                              # all groups + members
invest-monitor group create "Tax-Free" --description "Roth + HSA + 401k"
invest-monitor group add "Tax-Free" "PRU401K"
invest-monitor group remove "Tax-Free" "PRU401K"
invest-monitor group show "SCHAB"                      # which groups it's in
invest-monitor group delete "Tax-Free"

# ── Benchmark portfolios ───────────────────────────────────────────────────
invest-monitor benchmarks list                         # table per benchmark + weights
invest-monitor benchmarks fetch                        # pull 10y proxy prices via yfinance
invest-monitor benchmarks fetch --period 5y            # custom window

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
| 📊 Overview | Position table with current prices, P&L, and allocation donut. **🔍 Lookthrough toggle** disaggregates ETF/Fund positions into per-holding rows (vendor data) or per-sector synthetic rows (yfinance fallback) |
| 📈 Price History | Normalised price chart, cumulative returns, daily returns |
| 🥧 Exposure | Asset-type pie + sector bar with the same **🔍 Lookthrough toggle**. Tooltip lists which funds use vendor data vs yfinance fallback. Groups by (Type, Sector) under the hood |
| ⚠️ Risk | Volatility, VaR, correlation heatmap, return distribution, covariance heatmap, **Sector Stress Test** (Custom / Implied-from-driver-sector / 7 named scenarios), per-position stress P&L table + chart |
| 💵 Income | Annual income KPI, asset-type donut, payment-frequency-aware 12-month schedule, per-position detail |
| ✏️ Positions | Editable position table; add new positions |
| 🏢 Security Master | Edit asset metadata (name, type, sector, currency, **Income Rate**, **Payment Frequency**) |
| 📋 Trades | Record BUY/SELL trades; view trade history |
| 🔍 Lookthrough | Upload vendor holdings CSV, **or** fetch yfinance fund profile (asset_classes + sector_weightings) with one click |

**Multi-Portfolio Dashboard** (top to bottom):
- KPI strip (Portfolios, Positions, Total Cost, Current Value, Unrealised P&L)
- **Aggregate Exposure** section with the same **🔍 Lookthrough toggle** — asset-type donut + sector bar across *all* portfolios + a Top 15 underlying-exposures table that, under lookthrough, surfaces concentration (e.g. "I hold $X of AAPL via VTI / VOO / IWF combined")
- **Summary** table (1M/3M/6M/1Y returns, vol, VaR, drawdown) with merged-TOTAL row computed from a synthetic combined portfolio
- Cumulative-return, risk, and drawdown comparison charts
- **Income Projection** — annual / monthly / yield KPIs, per-portfolio table, donut by asset type, monthly payment schedule, per-position detail
- **Performance Attribution** — period selector (1M / 3M / 6M / 1Y / YTD / All), cumulative return + drawdown charts, end-of-period KPIs, top 10 contributors / detractors, stacked area of cumulative contribution by asset type. Each portfolio uses **v2 trade replay** (positions reconstructed from `trades.parquet` by cumulative-summing BUYs and SELLs) when trades are recorded, else **v1 static current positions**. Click **Refresh metrics** in the sidebar to (re)populate
- **Wealth Projection** — choose **Deterministic** (1–3 growth periods) or **Monte Carlo** (μ, σ per asset type, cross-asset correlation matrix, optional historical regime preset, fan chart with P10–P90 / P25–P75 bands, percentile table, per-portfolio outcome table, optional goal-probability KPI). Both methods have a shared **💰 Withdrawals (Safe Withdrawal Rate)** expander above the method-specific settings — enable it to subtract a fixed-real-dollar annual withdrawal from the portfolio. Deterministic gains a "Depletes at Year N" column; MC gains a survival-rate KPI, median-depletion-year KPI, and an optional "Survival across withdrawal rates" comparison table
- **🤖 Ask the Agents** — embedded chat panel with three tabs (Risk / Wealth / Research); each agent is lazily instantiated and keeps its own history, scoped per mode (live vs demo)

**⚙️ Production view** (new top-level view for scheduling & monitoring analytics jobs):
- KPI strip: Jobs / Failed (last) / Due now.
- Red banner the moment any job fails its last run.
- **Run all due now** primary button — executes every job whose interval has elapsed.
- One row per job (bordered container) with: name + description, interval, last run, status icon, **Enabled** toggle, and a per-job **Run** button. The last error message renders inline when present.
- **📅 Schedule with systemd** section — on Linux, install or uninstall a user-level systemd timer per job from one click. Shows current Active / Enabled state and the next-run time straight from `systemctl --user list-timers`. The generated `.service` and `.timer` content is viewable in an expander before install. On non-systemd platforms the section degrades to a "use cron" tip.
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

Two ways to teach the app what an ETF / Fund holds:

1. **Upload a vendor holdings CSV** (iShares, Vanguard, etc.) in the **🔍 Lookthrough** tab. The parser auto-detects common layouts (skips vendor metadata header rows) and fuzzy-matches columns for ticker, name, weight, sector, and asset class. Both `7.0`-style percentages and `0.07`-style fractions are accepted — detected by whether the column sums to > 1.5. The result lands in `fund_holdings.parquet` keyed on `(fund_ticker, as_of_date)`. **Ticker-level fidelity** — AAPL via VTI shows up as a real AAPL row.

2. **Click "Fetch Profile from yfinance"** in the same tab. This pulls `asset_classes` (stock / bond / cash / preferred / convertible / other position weights) and `sector_weightings` from `yfinance.Ticker(ticker).funds_data`. Result lands in `fund_profiles.parquet`. **Sector-level fidelity** — synthetic rows like "VTI → Technology", "VTI → Bond", "VTI → Cash". No individual constituent tickers.

### Resolution order

The `expand_lookthrough_rows` helper picks the highest-fidelity source available per fund:

| Priority | Source | Tag in `Source` column | Fidelity |
|---|---|---|---|
| 1 | `fund_holdings.parquet` | `vendor`   | Ticker-level: each constituent becomes a row keyed on its real ticker |
| 2 | `fund_profiles.parquet` | `yfinance` | Sector-level: equity portion spread across `sector_weightings`; bond / cash portions emit their own rows |
| 3 | (none)                  | `native`   | Kept as a single opaque fund row |

Activated by the **🔍 Apply ETF / Fund lookthrough** toggle that appears in:
- Single Portfolio → 📊 Overview tab (default OFF)
- Single Portfolio → 🥧 Exposure tab (default ON — preserves pre-existing behaviour)
- Multi-Portfolio Dashboard → Aggregate Exposure section (default OFF)

Dollar totals (Current Value, Total Cost, P&L) are invariant under lookthrough — they're redistributed across constituent rows, not re-valued. Share-level fields (Quantity, Cost Basis, Current Price) are `None` on synthetic rows since they're not meaningful for apportioned slices.

### Edge cases

- **Inverse / leveraged ETFs** (e.g. SH has `stockPosition = -1.0`, `cashPosition = 1.82`): negative weights are clipped to 0 and the remaining components are renormalised so they sum to 1. The "short equity" signal is lost, but total dollar value is preserved. An inverse-S&P ETF therefore looks through to ~100% Cash (its actual collateral composition) rather than negative equity.
- **Commodities ETFs** (e.g. PDBC, GLDM with `otherPosition` and no sector_weightings): the equity-like portion is bucketed as `Stock / Unknown`. You can override the asset_type in the Security Master if you'd rather track them as Commodity.
- **Asset-class data missing**: if a fund has no asset_classes at all (only sector_weightings), the equity portion is treated as 100% of the value. If neither is present, the helper falls through to the native (opaque) row.

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
| `groups.parquet` | Portfolio group registry: name, description, created_at |
| `portfolio_groups.parquet` | Many-to-many group ↔ portfolio: group_name, portfolio_name |
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

## Portfolio groups

Many-to-many tagging: a portfolio (e.g. SCHAB) can simultaneously belong to **Taxable** *and* **Brokerage**, while PRU401K belongs to **Tax-Free** and **Retirement**.

### Manage groups

Two equivalent surfaces:

- **Sidebar** → **🏷 Portfolio Groups** expander — create + name + describe groups, edit memberships via a multiselect, delete groups (member portfolios are untouched).
- **Single Portfolio → 📊 Overview tab** → a `🏷 Groups` multiselect lets you tag/untag the active portfolio without leaving the page. The sidebar's Active line shows current memberships as badges.
- **CLI** — `invest-monitor group create / list / add / remove / delete / show`.

### Group filter on the Multi-Portfolio Dashboard

When at least one group exists, a **Group filter** selectbox appears at the top of the dashboard. Selecting a group scopes **every** section below — KPI strip, Aggregate Exposure, Summary, Performance Attribution, Wealth Projection, Income Projection — to the portfolios in that group.

### View as combined portfolio

When a group is filtered, a **"View as combined portfolio"** toggle appears next to the filter. Flipping it on merges the group's member portfolios into a single synthetic entity named `"{group} (combined)"`:

- Positions in the same ticker across member portfolios are **quantity-summed**.
- Cost basis becomes the **weighted average** (`Σ qty_i × cb_i / Σ qty_i`).
- The merged portfolio is fed to every downstream section, so the Summary table collapses to one row, the Performance Attribution chart shows one cumulative-return line, and the Wealth Projection runs one fan instead of one per member portfolio.
- For the Performance Attribution time series, the daily metrics across members are aggregated by **summing `total_value` per date** and re-deriving `daily_return / cum_return / drawdown / rolling_vol_21d` from the merged value series.

This is the killer combo with **[Benchmarks](#benchmark-portfolios)**: filter to *Tax-Free*, flip "View as combined portfolio", overlay 60/40 — and you can see how your aggregate tax-free pot is performing vs the classic benchmark.

Dollar totals are invariant under combination: `Σ(member total_cost) = combined total_cost`, similarly for current value and market value.

## Benchmark portfolios

Eight built-in named recipes you can overlay on the **Performance Attribution** cumulative-return chart to see how your actual portfolios stack up against canonical mixes. Each benchmark is a weighted basket of public ETF proxies, so historical returns come from `Collector.collect_prices` (yfinance) and the existing `data/prices/` store.

| Benchmark | Recipe |
|---|---|
| **60/40 Classic** | 60% VTI (US Total Market) + 40% BND (Aggregate Bond) |
| **All Seasons (Dalio)** | 30% VTI + 40% TLT + 15% IEI + 7.5% GLD + 7.5% DBC |
| **Golden Butterfly** | 20% each: VTI, IJS (SmallCap Value), TLT, SHY, GLD |
| **Permanent Portfolio (Browne)** | 25% each: VTI, TLT, GLD, SHY |
| **Risk Parity (simple)** | 25% VTI + 55% TLT + 20% GLD (inverse-vol weighted) |
| **3-Fund Bogle** | 60% VTI + 20% VXUS + 20% BND |
| **Coffeehouse (Schultheis)** | 10% each: VTI / VTV / VB / VBR / VXUS / VNQ + 40% BND |
| **Larry Portfolio (Swedroe)** | 30% IJS + 70% IEI |

### First-time setup

```bash
invest-monitor benchmarks fetch          # 10y of proxy prices (default)
# or `--period 5y` / `--period max` to suit your horizon
```

This pulls 13 unique proxy tickers in one shot. They land in `data/prices/*.parquet` alongside everything else, so they're cached and reused.

### How they're computed

`benchmark_daily_returns(b, db)` returns the weighted-sum daily return series across the proxies. On each date, weights are **renormalised** across whichever proxies have a valid return that day — so a benchmark whose newest proxy has shorter history (e.g. VXUS) still produces a clean series on older dates, driven by the older proxies at their relative weights. `benchmark_cumulative(...)` and `benchmark_stats(...)` build on top.

### Using in the dashboard

In **Performance Attribution**:
- **Overlay benchmarks** multiselect → each pick renders as a dashed line on the cumulative-return chart, rebased to the same window start as your portfolios.
- **Benchmark stats over the same window** table — Period Return, Annualised Vol, Max Drawdown for each selected benchmark.
- **vs {primary benchmark}** delta table — for every portfolio, shows period-return − primary-benchmark-return so you can read off "did I beat 60/40 last quarter?" at a glance. The primary benchmark is the first one in your multiselect.

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

Three options, ordered from easiest to most manual:

**1 — One-click systemd install (Linux)**

In the dashboard's **⚙️ Production → 📅 Schedule with systemd** section, click **Install** next to any job. That writes the `.service` + `.timer` units to `~/.config/systemd/user/` and runs `systemctl --user enable --now`. From the CLI:

```bash
invest-monitor production schedule install refresh_attribution
invest-monitor production schedule install collect_prices
invest-monitor production schedule list
```

The timer fires the equivalent of `invest-monitor production run-now <job>` on its own schedule. Logs land in the systemd journal (`journalctl --user -u invest-monitor-refresh_attribution.service`). `Persistent=true` catches up missed runs when the machine wakes from sleep.

**2 — Cron (any platform)**

```cron
*/15 * * * * cd /path/to/invest_monitor && /usr/bin/uv run invest-monitor production run >> ~/.invest-monitor-cron.log 2>&1
```

`production run` only fires jobs whose interval has elapsed since their last successful run, so it's safe to call every minute or every hour.

**3 — Foreground daemon**

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

## Safe Withdrawal Rate (SWR)

The Multi-Portfolio Dashboard's Wealth Projection section has a shared **💰 Withdrawals (Safe Withdrawal Rate)** expander that works with both the Deterministic and Monte Carlo methods. Inspired by Bengen's 4% rule and the Trinity Study: a fixed-real-dollar annual withdrawal, taken at year-end, with optional inflation adjustment.

### Settings

| Field | Meaning |
|---|---|
| **Apply annual withdrawals** | Master on/off. When off, projection runs no-withdrawal as before. |
| **Primary withdrawal rate (%)** | Used for the fan chart + headline KPIs. Default 4.0%. The dollar amount = `primary_swr_pct × today's portfolio value`, then grown by inflation each year. |
| **Inflation adjustment (%/yr)** | Default 3.0%. Set to 0 for nominal-flat withdrawals. |
| **Rebalance to starting weights each year** | Default **ON**. After applying returns + withdrawal, snap each position back to its starting-year weight × current total. Off → positions drift as they compound at different rates. |
| **Compare additional rates** (MC only) | Multi-select from `[2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0]`. The simulation re-runs against the *same* return paths (RNG seed unchanged) so the comparison is apples-to-apples — only the withdrawal arithmetic changes. |

### Mechanics

Year-by-year, per portfolio:

1. Apply asset-type returns to each position independently.
2. Compute the total `T` after returns.
3. Withdraw `min(W × (1 + i)^(year−1), T)` where `W` is the initial dollar withdrawal and `i` is the inflation rate. Capping at `T` prevents negative balances.
4. Reduce each position pro-rata by `(T − actual_withdrawal) / T`.
5. **(Optional)** If rebalancing is on, snap each position to `year_total × starting_weight`. Without rebalancing, positions drift as they compound at different rates.
6. Floor at 0 to model a depleted portfolio.

The starting-year weights are captured at year 0 (`target_weight[i] = starting_value[i] / starting_total`), so the user's current portfolio mix *is* the rebalance target. No separate target-allocation input is required.

Rebalancing modestly improves survival under SWR — at 4% over 30y on a 60/40 portfolio, survival ticks up from ~71% (drift) to ~75% (rebalance), and P10 terminal value roughly doubles. The mechanism: trim positions that overshot, top up those that lagged, locking in profits from outperformers while preventing the bond ballast from being eroded.

### Outputs

**Deterministic**
- Chart title gains ` — withdrawing X%/yr (+Y% inflation)`.
- Milestone table gets a **Depletes** column showing `Year N` if a portfolio hits zero, else `—`. The TOTAL row's Depletes is `—` if any portfolio survives.

**Monte Carlo**
- KPI strip expands to 5 columns: P50 / P25 / P75 / **Survival @ primary_swr%** (share of paths with terminal value > 0) / **Median depletion year** (median first-zero year across the paths that did deplete).
- New **Survival across withdrawal rates** table appears when the compare list is non-empty. One row per SWR with: Survival %, P10 / P50 / P90 terminal value, Median depletion year.
- Fan-chart title surfaces the primary SWR and inflation adjustment.

### Reading the comparison table

Look for the highest SWR whose **Survival** column meets your target threshold (commonly 90–95% for conservative retirement planning). The same threshold applied across different regime presets (e.g. 1970s Stagflation vs 2010s Recovery in the MC Settings) tells you how sensitive your SWR is to the market environment you assume.

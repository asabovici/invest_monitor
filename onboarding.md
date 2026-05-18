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

### Anthropic API key

Required for any agent. Two ways to set it:

```bash
# 1. Project-local .env (auto-loaded by src/env.py via python-dotenv)
cp .env.example .env
# Edit .env and paste your key from https://console.anthropic.com → Settings → API Keys

# 2. Or export in your shell
export ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is gitignored. **Restart the Streamlit / CLI process after editing `.env`** — `load_dotenv()` runs at module import time and Streamlit's `st.rerun()` reuses already-imported modules, so a fresh process is required. A browser refresh is not enough.

### Demo mode (separate data store)

Want to record videos / share screenshots without exposing live data? Toggle **🎭 Demo mode** in the sidebar — every read switches to `data_demo/`, and a sample portfolio set is auto-seeded on first activation. Live `data/` is never touched. From the CLI:

```bash
invest-monitor demo seed         # idempotent
invest-monitor demo seed --reset # wipe & reseed
invest-monitor demo reset        # delete data_demo/
```

---

## Running the tool

```bash
# Launch the Streamlit dashboard (primary interface)
streamlit run src/app.py

# CLI commands
invest-monitor load portfolio.csv --name "My Portfolio"     # from CSV
invest-monitor portfolio create "Crypto"                    # empty portfolio
invest-monitor collect --period 1y
invest-monitor metrics refresh                              # daily returns/risk/attribution
invest-monitor report "My Portfolio"
invest-monitor portfolio list
invest-monitor agent --portfolio "My Portfolio"
invest-monitor wealth --portfolio "My Portfolio"
invest-monitor research --portfolio "My Portfolio"
invest-monitor demo seed                                    # populate data_demo/
```

Typical workflow: `load` (or `portfolio create` + record trades) → `collect` → `metrics refresh` → open dashboard or run agent.

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
├── env.py           — Loads .env into os.environ at import time
├── models.py        — Domain objects: Asset, Position, Portfolio, Constituent, AssetType
├── collector.py     — yfinance: prices, fund profiles, sector-ETF betas
├── reporting.py     — Risk, exposure, income, sector stress
├── attribution.py   — Daily security / portfolio / attribution metrics → parquet
├── production.py    — Scheduled-job runner: JobRunner + JOB_REGISTRY
├── scheduler.py     — systemd --user timer install / uninstall / status
├── benchmarks.py    — Named benchmark portfolios (60/40, All Seasons, …)
├── scenarios.py     — MC scenarios, cross-asset betas, sector stress presets,
│                      sector-ETF map, asset-class correlations, regime presets
├── demo.py          — Seed/reset the data_demo/ dataset
├── database/
│   └── database.py  — Parquet-backed data store with schema auto-migration
├── data/
│   └── ingestion.py — Portfolio CSV + ETF holdings CSV parsers
└── agent/
    ├── agent.py          — RiskAgent
    ├── skills.py         — Risk agent tools
    ├── wealth_agent.py   — WealthAgent
    ├── wealth_skills.py  — Wealth agent tools (includes scenario analysis)
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

### ETF / Fund lookthrough

Two sources of fund-composition data, plus a shared helper that picks the best available:

**Source 1: vendor holdings CSV (ticker-level)**

```
User uploads vendor holdings CSV in the Lookthrough tab
    → Ingester.parse_fund_holdings_csv()
        auto-detects header row (skips vendor metadata lines)
        fuzzy-matches columns for ticker/name/weight/sector/asset class
        normalises weights to fractions
    → Database.save_fund_holdings(fund_ticker, as_of_date, df)
        stored in fund_holdings.parquet keyed by (fund_ticker, as_of_date)
```

**Source 2: yfinance fund profile (sector-level)**

```
User clicks "Fetch Profile from yfinance" in the Lookthrough tab
    → Collector.fetch_fund_profile(ticker)
        reads yfinance.Ticker(ticker).funds_data:
          - asset_classes      (stockPosition, bondPosition, …)
          - sector_weightings  (technology, healthcare, …)
    → Database.save_fund_profile(fund_ticker, as_of_date, ac, sw)
        stored long-format in fund_profiles.parquet:
        (fund_ticker, as_of_date, category, key, weight)
```

**Shared helper: `expand_lookthrough_rows(portfolio, db, prices, enabled, yfinance_fallback=True)`** (in `src/app.py`)

```
Per position, resolution order:
  1) vendor holdings (fund_holdings.parquet)  → per-ticker rows tagged Source="vendor"
  2) yfinance profile (fund_profiles.parquet) → per-sector synthetic rows
       - equity portion (stock + preferred + convertible + other) spread across
         sector_weightings; tagged Source="yfinance"
       - bond / cash portions each emit their own row
       - inverse / leveraged ETFs (negative positions) get clip+renormalize:
         negatives → 0, then sum to 1, so dollar invariance holds
  3) native (no lookthrough or no data)        → opaque fund row, Source="native"

Returns a list of dicts with: Ticker, Name, Type, Sector, Quantity, Cost Basis,
Current Price, Total Cost, Current Value, P&L, P&L %, Via, Source, _synthetic.
Share-level fields (Quantity, Cost Basis, Current Price) are None on
synthetic rows.

Dollar totals (Current Value / Total Cost / P&L) are invariant under
lookthrough — they're redistributed across constituents, not re-valued.
```

Consumers:
- Single Portfolio → 📊 **Overview** tab — toggle default OFF.
- Single Portfolio → 🥧 **Exposure** tab — toggle default ON. After expansion,
  rows are grouped by `(Type, Sector)` to drive the donut + sector bar.
- Multi-Portfolio Dashboard → **Aggregate Exposure** section — toggle default
  OFF. Aggregates across all portfolios and renders donut + sector bar + a
  Top-15 underlying-exposures table (which is most useful with lookthrough on,
  since it surfaces cross-fund concentration like "AAPL appears in VTI, VOO,
  IWF…").

---

## Key concepts

### Domain model

```
Portfolio
  └── List[Position]
        ├── asset: Asset
        │     ├── ticker, name, asset_type, currency, sector
        │     ├── income_rate: float       ← Stock/ETF/Fund → $/share/payment
        │     │                              Bond/CD/Cash  → annual %
        │     ├── payment_frequency: int   ← 1 | 2 | 4 | 12  (annual income for
        │     │                              equities = qty × rate × frequency)
        │     └── constituents: List[Constituent]  ← legacy ETF look-through
        ├── quantity: float
        └── cost_basis: float  ← ALWAYS per share, never total
```

`AssetType` now also has `CD` — Certificates of Deposit. They get the same constant-1.0 synthetic price series as `Cash` so portfolios composed entirely of cash/CDs still produce risk metrics rather than "No price data".

### Risk metrics

- **Volatility** — annualized std dev of daily returns × √252
- **Historical VaR (95%)** — 5th percentile of observed daily returns
- **Monte Carlo VaR (95%)** — parametric: 10,000 samples from N(mean, std), take percentile
- **Covariance matrix** — pairwise annualized covariances; useful for diversification analysis

### Safe Withdrawal Rate (Wealth Projection)

Lives inside the Wealth Projection block in `src/app.py`. Bengen-style fixed-real-dollar withdrawal applied year-by-year, with optional annual rebalancing back to starting-year weights. Both Deterministic and Monte Carlo paths follow the same recipe:

```
base_withdrawal = starting_value × (primary_swr_pct / 100)
target_weights  = [pos_i_value / starting_value for each position]  # captured once at year 0

for yr in 1..horizon:
    # 1) Apply returns to each position independently.
    pos_values *= (1 + return_for_year)
    pos_values = max(0, pos_values)

    if apply_withdrawals:
        # 2) Subtract the year's withdrawal pro-rata across positions.
        wd_this_year = base_withdrawal × (1 + inflation_pct/100) ^ (yr-1)
        actual = min(wd_this_year, total)
        pos_values *= (total - actual) / total

        # 3) Optional rebalance to starting weights — trims winners, tops up
        #    laggards, prevents drift away from the target mix.
        if rebalance_annually:
            year_total = pos_values.sum()
            pos_values = year_total × target_weights
```

Per-portfolio state is maintained as a `(n_sims, n_positions)` numpy array in MC mode (and a plain list in Deterministic) so the simulation can compound positions independently while subtracting withdrawals pro-rata across them. The MC rebalance step is a single broadcast `pos_values = year_total[:, None] × tgt_weights[None, :]` — vectorised over all sims in one op, so the perf hit is negligible. For 2k sims × 30y × 30 positions the full loop completes in well under a second.

**Compare mode (MC only)**: `_simulate(swr_pct)` is a closure over the pre-drawn `type_returns` array. Re-running it for each comparison SWR is cheap because the random draws are reused — only the withdrawal arithmetic changes. The survival table iterates compare_swrs ∪ {primary} and reports `(survival %, P10/P50/P90 terminal, median depletion year)` for each.

**Outputs:**
- `_depletion_year(paths)` finds the first year each path drops to ≤ $1e-6 and returns the median over depleted paths (`None` if no path depletes).
- Deterministic milestone table grows a **Depletes** column; TOTAL row reports `"—"` if any portfolio still has money, else the latest depletion year.
- MC KPI strip grows to 5 columns: P50 / P25 / P75 / Survival % / Median depletion year.

When `apply_withdrawals=False` the behaviour is identical to pre-SWR code (chart, KPIs, tables all unchanged), so the feature is purely additive.

---

## Data storage

All data lives under `data/` as Parquet files (gitignored). Demo data is the same schema, just under `data_demo/`. Schemas auto-migrate on `Database(...)` init — missing columns are backfilled with safe defaults (`income_rate=0`, `payment_frequency=1`, etc.).

```
data/
├── assets.parquet                      — ticker, name, asset_type, currency, sector,
│                                          income_rate, payment_frequency
├── portfolios.parquet                  — name, created_at
├── positions.parquet                   — portfolio_name, ticker, quantity, cost_basis (per share)
├── constituents.parquet                — parent_ticker, constituent_ticker, weight (legacy)
├── trades.parquet                      — trade_id, portfolio_name, ticker, side, qty,
│                                          trade_price, trade_date
├── fund_holdings.parquet               — fund_ticker, as_of_date, holding_ticker,
│                                          holding_name, weight, sector, asset_type
├── fund_profiles.parquet               — long format: fund_ticker, as_of_date,
│                                          category ("asset_class" | "sector"), key, weight
├── sector_betas.parquet                — sector_a, sector_b, beta, as_of_date
├── daily_security_metrics.parquet      — date, ticker, price, daily_return, cum_return,
│                                          rolling_vol_21d
├── daily_portfolio_metrics.parquet     — date, portfolio_name, total_value, daily_return,
│                                          cum_return, rolling_vol_21d, drawdown, max_drawdown
├── daily_attribution.parquet           — date, portfolio_name, ticker, weight,
│                                          position_return, contribution_to_return,
│                                          asset_type, sector
├── production_jobs.parquet             — job_name, enabled, interval_minutes,
│                                          last_run_at, last_status, last_error,
│                                          last_duration_seconds
├── production_runs.parquet             — run_id, job_name, started_at, ended_at,
│                                          status, error_message, details,
│                                          duration_seconds
├── groups.parquet                      — portfolio group registry:
│                                          name, description, created_at
├── portfolio_groups.parquet            — many-to-many group ↔ portfolio:
│                                          group_name, portfolio_name
└── prices/
    └── {TICKER}.parquet                — date-indexed daily close prices
```

The `daily_*.parquet` files are populated by `AttributionEngine.refresh_all()` (CLI: `invest-monitor metrics refresh`, UI: **Refresh metrics** button in sidebar — always visible, independent of which portfolio is open). Refresh is incremental — it re-walks the last 30 days from the latest stored date plus any new dates.

**Position reconstruction modes** (picked automatically per portfolio):

- **v2 — `compute_portfolio_history_from_trades`** — used when `trades.parquet` has rows for the portfolio. Pivots the trade ledger to a `(date × ticker)` delta matrix (BUY +, SELL −), reindexes to the price calendar, cumulative-sums to running quantities, multiplies by daily prices. Each historical date reflects actual holdings on that date. Quantities before the first trade are 0; positions are clipped at ≥ 0 to guard against SELLs exceeding recorded BUYs.
- **v1 — `compute_portfolio_history`** — fallback when no trades are recorded. Uses today's positions across the whole price history.

The refresh-summary dict's `modes` key reports which path each portfolio took. The dashboard success toast echoes this.

### Production scheduling (`src/production.py`)

`JobRunner` wraps every callable in `JOB_REGISTRY` with persistence + error capture. Each run lands in `production_runs.parquet`; the job's `last_status` and `last_error` flip on `production_jobs.parquet` so the dashboard's Production view can highlight failures.

Built-in jobs:

| Job | Interval | Wraps |
|---|---|---|
| `collect_prices`        | 24h | `Collector.update_all_assets(period="1mo")` |
| `refresh_attribution`   | 24h | `AttributionEngine.refresh_all()` |
| `refresh_sector_betas`  |  7d | `Collector.fetch_sector_betas(years=20)` + `Database.save_sector_betas` |
| `refresh_fund_profiles` |  7d | For every held ETF/Fund: `fetch_fund_profile` → `save_fund_profile` |

Adding a new job:

```python
# In src/production.py
def _my_job(db: Database) -> dict:
    ...
    return {"...": "result summary, will be json.dumps'd into production_runs.details"}

JOB_REGISTRY["my_job"] = {
    "callable": _my_job,
    "interval_minutes": 60 * 24,
    "description": "Brief description shown in the dashboard.",
}
```

The next `JobRunner` instantiation auto-seeds `production_jobs.parquet` with a row for `my_job` (enabled by default, status `never_run`). No DB migration needed.

To trigger jobs from outside the dashboard:

```bash
invest-monitor production status                # job table + due flag
invest-monitor production run                   # one-shot: run only what's due (cron-friendly)
invest-monitor production run-now my_job        # force-run a single job
invest-monitor production daemon --check-every 60   # long-running loop
```

### Scheduling with systemd (`src/scheduler.py`)

On Linux, instead of cron you can install user-level systemd timers from the dashboard or CLI. The scheduler module:

- Detects `systemctl --user` availability (`is_systemd_available()`).
- Writes `.service` + `.timer` units to `~/.config/systemd/user/`.
- Service is `Type=oneshot` and `ExecStart`s `invest-monitor production run-now <job>` so each fire goes through the same code path as a manual run, captures the same logs, and updates `production_jobs.parquet` the same way.
- Timer uses `OnBootSec=5min`, `OnUnitActiveSec=<interval>min`, `Persistent=true` (catches up runs missed while the machine was off).

`_detect_runner()` picks the most reliable launcher: `uv run invest-monitor` if uv is on PATH and we're in the project root, then `invest-monitor` binary, then `python3 -m src.cli`. `WorkingDirectory` is set to the current cwd so relative paths in `data/` keep working.

CLI:

```bash
invest-monitor production schedule list
invest-monitor production schedule install refresh_attribution
invest-monitor production schedule install collect_prices --interval 720   # override
invest-monitor production schedule uninstall refresh_attribution
```

The Production view's **📅 Schedule with systemd** section renders the same controls per job, plus a "Preview unit files" expander so you can review the generated `.service` / `.timer` content before clicking Install.

Inspect any file:

```python
import pandas as pd
pd.read_parquet("data/assets.parquet")
pd.read_parquet("data/fund_holdings.parquet")
pd.read_parquet("data/daily_attribution.parquet").query("portfolio_name == 'My Portfolio'").tail(20)
pd.read_parquet("data/prices/AAPL.parquet").tail(10)
```

---

## Streamlit dashboard tabs

The dashboard has two views (sidebar radio: Single Portfolio / Multi-Portfolio Dashboard).

**Single Portfolio tabs (nine):**

| Tab | Contents |
|-----|----------|
| 📊 Overview | Position table with P&L, allocation donut. **🔍 Lookthrough toggle** (default OFF) replaces fund positions with per-holding rows (vendor) or per-sector synthetic rows (yfinance fallback) |
| 📈 Price History | Normalised prices, cumulative returns, daily returns |
| 🥧 Exposure | Asset-type pie, sector bar — driven by `expand_lookthrough_rows`. **🔍 Lookthrough toggle** (default ON) controls whether ETF/Fund positions are disaggregated via vendor holdings → yfinance fallback → native |
| ⚠️ Risk | Volatility, VaR, correlation heatmap, return distribution, covariance heatmap, **Sector Stress Test** (Custom / Implied-from-driver-sector / named scenarios) |
| 💵 Income | KPI strip + asset-type donut + payment-frequency-aware 12-month schedule + per-position detail |
| ✏️ Positions | Editable position table, add new positions |
| 🏢 Security Master | Edit asset metadata (incl. **Income Rate**, **Payment Frequency**); add new securities |
| 📋 Trades | Record BUY/SELL trades, view trade history |
| 🔍 Lookthrough | Upload vendor holdings CSV **or** fetch yfinance fund profile (asset_classes + sector_weightings) |

**Multi-Portfolio Dashboard** (top to bottom):
- KPI strip (Portfolios, Positions, Total Cost, Current Value, Unrealised P&L)
- **Aggregate Exposure** — asset-type donut + sector bar + Top-15 underlying-exposures table, all driven by `expand_lookthrough_rows`. The **🔍 Lookthrough toggle** (default OFF) determines whether ETF/Fund positions across *all* portfolios are disaggregated. With lookthrough on, the Top-15 table surfaces cross-fund concentration (e.g. "$X of AAPL via VTI + VOO + IWF")
- Summary table with merged-TOTAL row (returns, vol, VaR, drawdown)
- Cumulative-return / risk / drawdown comparison charts
- **Income Projection** (annual/monthly/yield KPIs + per-portfolio + donut + monthly schedule + per-position)
- **Performance Attribution** (cum-return + drawdown over a chosen period, top 10 contributors/detractors, cumulative contribution by asset type — populated from the `daily_*.parquet` files)
- **Wealth Projection** — Deterministic or Monte Carlo (with cross-asset correlation matrix and historical regime presets). Optional shared **💰 Withdrawals (Safe Withdrawal Rate)** expander: Bengen-style fixed-real-dollar withdrawal applied year-by-year, pro-rata across positions, with optional inflation growth. In MC mode there's a "Compare with" multiselect that re-runs the simulation against the same return paths for multiple SWRs and renders a survival table
- **🤖 Ask the Agents** — embedded chat panel with Risk / Wealth / Research tabs (independent histories per agent, scoped per mode)

> Performance attribution and embedded agent chat live exclusively on the Multi-Portfolio Dashboard view. Income, stress test, etc. are mirrored in the Single Portfolio tabs.

**⚙️ Production view** (third top-level option):
- KPI strip: Jobs / Failed (last) / Due now.
- **Run all due now** + per-job **Run** buttons and an **Enabled** toggle (writes back to `production_jobs.parquet`).
- Two log tabs: **📜 Recent Runs** and **🚨 Issues** (errors only).
- Used to monitor the same jobs that `invest-monitor production run` fires from cron / systemd.

---

## Scenario analysis (WealthAgent)

The wealth agent (`invest-monitor wealth`) has two skills for stress-testing growth projections:

**`list_scenarios`** — shows all built-in scenarios and the cross-asset beta table.

**`run_scenario_analysis`** — Monte Carlo projection with named scenario phases and/or beta-implied cross-asset shocks.

### Named scenarios

| Scenario | What it models |
|---|---|
| `base` | No adjustment (same as standard MC) |
| `market_crash` | 2008-style: instant -15% drop → bear → slow recovery |
| `mild_correction` | 10–15% dip over 3 months, then rebound |
| `prolonged_low_growth` | Lost decade: returns at 20% of historical average |
| `stagflation` | Flat-to-negative real returns, elevated volatility |
| `bull_run` | 2× historical returns, compressed volatility |
| `flash_crash_recovery` | -12% flash crash then V-shaped recovery |
| `double_dip` | Two bear legs separated by a false rally |
| `rate_shock` | 2022-style rate spike with permanent lower valuations |

### Beta-implied shocks

Shock one asset class and the engine computes implied shocks for all others using historical cross-asset betas (relative to equities):

| Asset class | Beta vs equities |
|---|---|
| Stock | 1.00 |
| ETF | 0.85 |
| Fund | 0.70 |
| Bond | −0.15 (often rallies in crashes) |
| Crypto | 0.75 |
| Cash | 0.00 |

**Example prompt:** *"What happens to my SCHAB portfolio under a market crash if equities drop 40%?"* — use `scenario_name="market_crash"`, `shocked_asset_class="Stock"`, `shock_return_pct=-40`.

Both features can be combined. The output includes P5–P95 percentile outcomes, a goal probability if `goal_amount` is set, and a breakdown of implied shocks per asset class.

---

## Things to watch out for

- **`cost_basis` is per share**, not total. `Portfolio.total_cost()` = Σ (quantity × cost_basis). Storing total cost causes double-multiplication.
- **`Type` column must match AssetType enum exactly**: `Stock`, `Bond`, `ETF`, `Fund`, `Cash`, `CD`, `Crypto` — not `stock`, `Equity`, etc.
- **`income_rate` has dual semantics**: Stock/ETF/Fund → **$/share/payment** (annual = qty × rate × payment_frequency); Bond/CD/Cash → **annual %**. Get this wrong and your annual income will be off by `payment_frequency`× for equities. UI labels and table formatters use the row's asset type to render the unit suffix.
- **`collect` before `report`/agent** — risk metrics need price data in the DB.
- **Run `metrics refresh` to populate the Performance Attribution section** — it reads from the `daily_*.parquet` files. The section shows an info banner with the command if the files are empty.
- **Attribution mode is auto-selected per portfolio**: v2 trade replay when `trades.parquet` has rows for that portfolio, v1 static current otherwise. To force-upgrade a CSV-imported portfolio to v2, record its trades in the **📋 Trades** tab and re-run **Refresh metrics**. The refresh summary's `modes` dict tells you which path each portfolio took.
- **v2 quirks worth knowing**: trades on non-trading days snap to the next trading day so no quantity is lost; running positions are floored at 0 (no shorting modelled); positions before the very first trade are 0, so attribution rows simply don't exist for that pre-history window.
- **Production runner state is per-data-dir**: `production_jobs.parquet` and `production_runs.parquet` live in `data/` and `data_demo/` separately, so demo mode has its own independent schedule + run log. Flipping demo mode while the daemon is running against the live dir is safe — they don't share state.
- **`production run` is idempotent and cron-friendly**: it only fires jobs whose interval has elapsed, so running it every minute does nothing most of the time. Don't introduce side-effects in a job that aren't safe under re-execution; the runner doesn't dedupe within a single interval.
- **systemd-installed timers run `invest-monitor production run-now <job>`, not `production run`**: each timer drives its own job, ignoring the in-DB interval and the per-job `enabled` toggle. If you uncheck **Enabled** in the dashboard while the systemd timer is installed, the timer still fires — uninstall the timer or use the manual `production run` path if you want the toggle to gate firing.
- **`WorkingDirectory` in the generated unit is set to the CWD at install time** (typically the project root). If you move the project, run `production schedule uninstall <job>` then `install <job>` again to regenerate units with the new path.
- **Inverse / leveraged ETFs under lookthrough**: when yfinance reports negative `stockPosition` (e.g. SH = −1.0 with cashPosition 1.82), `expand_lookthrough_rows` clips negatives to 0 and renormalises the remaining components so they sum to 1. This preserves dollar invariance (total Current Value before vs after lookthrough is unchanged within float-noise tolerance, ~$10 on $600k+ portfolios) but **loses the "short equity" signal** — an inverse-S&P ETF looks through to ~100% Cash, which is its actual collateral composition. If you need the short-exposure dimension, leave lookthrough off for those holdings.
- **Portfolio groups are many-to-many, not partitions**: A single portfolio can belong to *N* groups (e.g. SCHAB ∈ {Taxable, Brokerage}). The dashboard filter scopes to one group at a time; "combined view" merges *that group's* member portfolios into a synthetic entity but doesn't double-count anything. Adding the same `(group, portfolio)` pair twice is a no-op (idempotent). Deleting a group removes its memberships; the member portfolios themselves are untouched.
- **Combined view = position merge, not metric average**: When the user toggles "View as combined portfolio", positions across members are quantity-summed with a weighted-average cost basis (preserves total cost exactly). Daily portfolio metrics for the synthetic entity are derived by summing per-day `total_value` across members and re-computing `daily_return`, `cum_return`, `drawdown`, `rolling_vol_21d` from the merged value series — **not** by averaging the members' pre-computed metrics, which would mis-weight portfolios of different sizes.
- **SWR rebalancing target = starting-year weights**: the rebalance step (when on) snaps each position back to `current_total × (starting_value_i / starting_total)`. The user's current portfolio mix at year 0 *is* the implicit target — there's no separate target-allocation input. If you want a different rebalance target (e.g. a glide path from 80/20 → 40/60 over retirement), that's a follow-up — call it out and we'll add it.
- **Pro-rata withdrawal vs rebalance order matters**: withdrawals are subtracted *before* the rebalance step, not after. So the "annual rebalance" zeroes the drift that built up during that year's returns AND the post-withdrawal asset mix. With rebalance OFF, the drift accumulates and withdrawals shrink the drifted mix uniformly.
- **SWR withdrawal cap at zero**: when the year's withdrawal exceeds the total, the cap takes only what's left and the portfolio hits exactly 0 that year. Subsequent years' returns × 0 = 0, so once depleted, depleted. Realistic for retirement modelling; less realistic if you actually have other cash sources to fall back on (those aren't modelled).
- **`portfolios.parquet` and `positions.parquet` must stay in sync** — writing one without the other leaves the portfolio invisible to `portfolio list`. `Database.save_portfolio()` handles both atomically. `get_portfolio()` was extended to return an empty Portfolio if the name exists in `portfolios.parquet` but has no positions (so newly-created empty portfolios load correctly).
- **Adding a column to a parquet file is auto-migrated** — `Database._init_store()` now backfills missing columns with defaults from `_MIGRATION_DEFAULTS`. So adding a column requires (a) declaring it in the schema dict, (b) adding a default in `_MIGRATION_DEFAULTS` if non-`None`, (c) reading/writing it in the relevant methods. No more manual parquet deletion.
- **Streamlit cached resources are keyed by `data_dir`** — `get_db()` and `get_reporting()` use `@st.cache_resource`-wrapped factories `_make_db(data_dir)` / `_make_reporting(data_dir)`, so live and demo modes don't share cached state. The `fetch_prices` cache is also keyed on the active directory.
- **`.env` is loaded on module import only** — `src/env.py` calls `load_dotenv()` at import time, which Python caches in `sys.modules`. After editing `.env`, **restart Streamlit / the CLI process** entirely; a browser refresh or `st.rerun()` won't re-load.
- **Run from project root** — `data/` path is relative; running from `src/` creates a new empty store in the wrong place.
- **String columns with all-NaN values** — pandas infers dtype as `float64`, which breaks Streamlit's `TextColumn` config. `Database.get_all_assets()` and `get_portfolio()` cast `name`, `sector`, `currency` to `str` / `None` on read. Do the same for any new string columns added to parquet files.

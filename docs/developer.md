# Developer Guide

## Codebase map

```
src/
├── app.py           — Streamlit dashboard (primary UI)
├── cli.py           — Click CLI entry point
├── env.py           — Loads .env into os.environ at module import time
├── models.py        — Domain objects: Asset, Position, Portfolio, AssetType
├── collector.py     — yfinance: prices, fund profiles, sector-ETF betas
├── reporting.py     — Risk, exposure, income, sector stress
├── attribution.py   — Daily metrics + v1/v2 attribution reconstruction
├── scenarios.py     — MC scenarios, betas, sector stress presets, regime presets
├── benchmarks.py    — Named benchmark portfolios (60/40, All Seasons, …)
├── agent_summaries.py — JSON store + Haiku summariser for past agent chats
├── production.py    — Scheduled-job runner (JobRunner + JOB_REGISTRY)
├── scheduler.py     — systemd --user timer install / uninstall / status
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

## How key pieces connect

### Loading a portfolio

```
Ingester.load_portfolio_from_csv(path, name)
    → builds Asset objects, calls Database.add_asset() each
    → Database.save_portfolio(portfolio)
        atomic upsert of portfolios.parquet + positions.parquet
```

### Collecting prices

```
Collector.update_all_assets(period)
    → queries Database.get_all_tickers()
    → yfinance.download(...) per ticker
    → Database.save_prices(ticker, df)
```

### Attribution

```
AttributionEngine.refresh_all()
    For each portfolio:
        if trades.parquet has rows for it → compute_portfolio_history_from_trades (v2)
        else                              → compute_portfolio_history          (v1)
    → Database.save_daily_*  (upserts keyed on (date, …))
```

### Lookthrough

```
expand_lookthrough_rows(portfolio, db, prices, enabled=True, yfinance_fallback=True)
    For each position:
      1. vendor holdings (fund_holdings.parquet)  → ticker-level rows
      2. yfinance profile (fund_profiles.parquet) → sector-level synthetic rows
      3. native                                   → opaque fund row
```

## Things to watch out for

!!! danger "`cost_basis` is per-share, never total"
    `Portfolio.total_cost()` = `Σ(quantity × cost_basis)`. Storing total cost causes double-multiplication. Bug hit in April 2026 — always use per-share.

!!! danger "Streamlit hot-reload breaks enum identity"
    `pos.asset.asset_type in (AssetType.ETF, ...)` returns False after a hot-reload because Python re-imports `AssetType` as a new class. Always compare on `.value`:
    ```python
    pos.asset.asset_type.value in ("ETF", "Fund")
    ```

!!! warning "`income_rate` dual semantics"
    Stock / ETF / Fund → `$/share/payment` (annual = qty × rate × payment_frequency).
    Bond / CD / Cash → annual `%`. Get this wrong and equity annual income will be off by a factor of `payment_frequency`.

!!! warning "Inverse / leveraged ETF lookthrough"
    `expand_lookthrough_rows` clips negative `asset_class` weights to 0 and renormalises so they sum to 1. Preserves dollar invariance (~$10 noise on $600k+) but loses the "short equity" signal. SH (inverse S&P) ends up looking like ~100% Cash, which is its actual collateral composition.

!!! info "SWR rebalance target = starting-year weights"
    The rebalance step (when on) snaps each position to `current_total × (starting_value / starting_total)`. The user's current portfolio mix at year 0 is the implicit target. Glide-path targets aren't supported yet.

!!! info ".env loads only on module import"
    `src/env.py` calls `load_dotenv()` at module import; Python caches imports across Streamlit reruns. Editing `.env` requires a full process restart, not a browser refresh.

!!! info "Cached resources are keyed by data_dir"
    `get_db()` / `get_reporting()` use `@st.cache_resource`-wrapped factories `_make_db(data_dir)` / `_make_reporting(data_dir)`. Live and demo modes don't share cached state. `fetch_prices` cache is also keyed on active dir.

!!! info "String columns with all-NaN values"
    pandas infers dtype as `float64`, breaking Streamlit's `TextColumn`. `Database.get_all_assets()` and `get_portfolio()` cast `name`, `sector`, `currency` to `str`/`None` on read. Do the same for any new string columns added to parquet files.

!!! info "Conversation summaries use Haiku, not Opus"
    `agent_summaries.summarize_conversation()` calls `claude-haiku-4-5-20251001` rather than the main agent's Opus model. Summarisation is a fixed-form compression task — Haiku does it cheaply and quickly. The main agent stays on Opus for actual reasoning. The summary JSON lives at `data/agent_summaries.json` (per-data-dir, so demo and live are separate) and stores the **full transcript** alongside the summary, so you can re-summarise with a different model later if you want.

!!! info "Loaded context primes the agent — it doesn't replay the transcript"
    `build_context_prompt()` formats selected summaries as a single user message that explicitly asks the agent to *acknowledge briefly and wait* for the next question. The transcript itself isn't replayed turn-by-turn (that would inflate token use), only the compressed summary text. Treat saved summaries as memory aids, not lossless logs.

!!! info "Portfolio groups are many-to-many, not partitions"
    A single portfolio can belong to *N* groups (e.g. SCHAB ∈ {Taxable, Brokerage}). The dashboard filter scopes to one group at a time; **"View as combined portfolio"** merges *that group's* member portfolios into a synthetic entity (quantity-summed positions, weighted-average cost basis) but doesn't double-count anything. `db.add_to_group` is idempotent. Deleting a group removes its memberships; member portfolios themselves are untouched.

!!! info "Combined view: position merge, not metric average"
    When the user toggles "View as combined portfolio", daily portfolio metrics for the synthetic entity are derived by summing per-day `total_value` across members and re-computing `daily_return`, `cum_return`, `drawdown`, `rolling_vol_21d` from the merged value series — **not** by averaging the members' pre-computed metrics, which would mis-weight portfolios of different sizes.

!!! info "Schema migration is automatic"
    `Database._init_store()` backfills missing columns with defaults from `_MIGRATION_DEFAULTS`. To add a new column:
    1. Declare it in the schema dict.
    2. Add a default in `_MIGRATION_DEFAULTS` if non-`None`.
    3. Read/write it in the relevant methods.

!!! info "`production run` is idempotent"
    Only fires jobs whose interval has elapsed since their last successful run. Don't introduce side-effects in a job that aren't safe under re-execution.

!!! info "systemd `WorkingDirectory` is captured at install"
    `_detect_runner()` records the CWD when you ran `production schedule install`. If you move the project, uninstall then reinstall.

## Domain model

```python
@dataclass
class Asset:
    ticker: str
    asset_type: AssetType
    name: str
    currency: str = "USD"
    sector: Optional[str] = None
    income_rate: float = 0.0
    payment_frequency: int = 1
    constituents: List[Constituent] = field(default_factory=list)

@dataclass
class Position:
    asset: Asset
    quantity: float
    cost_basis: float    # PER SHARE

@dataclass
class Portfolio:
    name: str
    positions: List[Position] = field(default_factory=list)

    def total_cost(self) -> float:
        return sum(p.quantity * p.cost_basis for p in self.positions)
```

## Build the docs locally

```bash
uv sync --extra docs
uv run mkdocs serve   # http://127.0.0.1:8000
uv run mkdocs build   # static site → site/
```

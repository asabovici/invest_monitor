# Data directory

This is the **live** dataset. A parallel **demo** dataset lives at
`../data_demo/` with identical structure and gitignored sample data — switch
between them via the Streamlit sidebar toggle or `--data-dir data_demo`
on any CLI / service call.

The directory itself is committed (so this `CLAUDE.md` lives in git) but
`*.parquet`, `*.csv`, and `reports/` are all gitignored. The only file
you'll see here when cloning fresh is this one.

## File layout

```
data/
├── assets.parquet                 # asset master: ticker, name, asset_type,
│                                  # currency, sector, income_rate, payment_frequency
├── constituents.parquet           # legacy inline ETF lookthrough (composite asset → weights)
├── portfolios.parquet             # name, created_at
├── positions.parquet              # portfolio_name, ticker, quantity, cost_basis (PER SHARE)
├── trades.parquet                 # ledger: trade_id, portfolio_name, ticker, side, qty, price, date
├── fund_holdings.parquet          # vendor-uploaded ETF/fund holdings (per (fund_ticker, as_of_date))
├── fund_profiles.parquet          # yfinance asset_classes + sector_weightings per fund ticker
├── sector_betas.parquet           # pairwise sector betas (long: sector_a, sector_b, beta)
├── daily_security_metrics.parquet # per (date, ticker): price, daily_return, cum_return, rolling_vol_21d
├── daily_portfolio_metrics.parquet# per (date, portfolio_name): total_value, daily_return, cum_return,
│                                  # rolling_vol_21d, drawdown, max_drawdown
├── daily_attribution.parquet      # per (date, portfolio_name, ticker): weight, position_return,
│                                  # contribution_to_return, asset_type, sector
├── groups.parquet                 # portfolio group registry (name, description)
├── portfolio_groups.parquet       # many-to-many group ↔ portfolio
├── production_jobs.parquet        # scheduled-job config + last-run status
├── production_runs.parquet        # append-only production run log
├── agent_summaries.json           # saved summaries of past agent chats (Risk/Wealth/Research/PM/CIO)
├── reports/                       # markdown reports emitted by export_report skill (gitignored)
└── prices/{TICKER}.parquet        # daily Close prices per ticker, DatetimeIndex
```

## Conventions you must know

- **`cost_basis` is per share**, never total. `Portfolio.total_cost()` is
  `Σ(quantity × cost_basis)`. Storing total cost causes double-multiplication.
  CSV ingestion (`src/data/ingestion.py`) divides `CostBasis / Quantity` on
  the way in.
- **Cash / CD synthetic prices**: `Database.get_historical_prices()` backfills
  missing tickers with constant `1.0` (held at par). Genuine "no data"
  returns are also `1.0` — services document this in their
  `LatestPriceResponse` docstring. To detect a true gap, inspect history
  for variation.
- **Demo vs live**: `data_demo/` has demo portfolios (`Demo Cash & CDs`,
  `Demo Retirement`, `Demo Brokerage`) seeded by `invest-monitor demo seed`.
  Reseed safely with `--reset`. Both Streamlit and the agents pick a dir
  from the same `_active_data_dir()` helper / `X-Data-Dir` header.
- **Schema auto-migration** happens in `Database._init_store()` — new columns
  on existing parquets get default-filled (`income_rate=0.0`,
  `payment_frequency=1`, …). Adding a column is safe across versions.

## Refreshing daily metrics

`daily_security_metrics`, `daily_portfolio_metrics`, and `daily_attribution`
are produced by `AttributionEngine.refresh_all()`. Trigger via:

```bash
uv run invest-monitor metrics refresh --data-dir data
```

Reports that read these tables (`/reports/attribution`, benchmark
overlays, the Performance Attribution tab) all return empty/zeroed
responses when the parquet is empty — they don't 500.

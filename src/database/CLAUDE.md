# Database — parquet-backed storage

A single class, `Database`, that owns every parquet file under a `data_dir`.
Other modules read/write only through it; nothing else opens parquet files
directly. Heavy reads use DuckDB; writes use pandas + pyarrow.

## File layout

Each `Database(data_dir)` materialises this tree (creating missing files
on first call via `_init_store`):

```
<data_dir>/
├── assets.parquet
├── constituents.parquet
├── portfolios.parquet
├── positions.parquet
├── trades.parquet
├── fund_holdings.parquet
├── fund_profiles.parquet
├── sector_betas.parquet
├── daily_security_metrics.parquet
├── daily_portfolio_metrics.parquet
├── daily_attribution.parquet
├── groups.parquet
├── portfolio_groups.parquet
├── production_jobs.parquet
├── production_runs.parquet
└── prices/{TICKER}.parquet         # one file per ticker, DatetimeIndex
```

`data/CLAUDE.md` has the per-file column inventory.

## Core operations

| Method | Purpose | Reducer-style? |
|---|---|---|
| `add_asset(asset)` | Upsert one row in `assets.parquet` (and constituents) | Yes — last-write-wins on `ticker` |
| `save_portfolio(portfolio)` | Upsert portfolio metadata + **replace** all its positions | Replace semantics |
| `list_portfolios()` | DuckDB query, newest-first by `created_at` | — |
| `get_portfolio(name)` | DuckDB join positions + assets + constituents → domain `Portfolio` | Raises `ValueError` if missing |
| `delete_portfolio(name)` | Drop the row + drop its positions | Silent no-op if missing |
| `record_trade(...)` | Append to `trades.parquet` + apply BUY/SELL with average-cost blending | — |
| `update_positions_direct(...)` | Replace positions without going through trades | Last-write-wins |
| `save_prices(ticker, df)` | Merge new dates into `prices/{ticker}.parquet`, last-write wins per date | — |
| `get_historical_prices(tickers, start)` | Join all per-ticker files; **cash-style backfill** for missing tickers | See below |
| `save_daily_*` / `get_daily_*` | Upsert keyed on `(date, ticker)` / `(date, portfolio_name, ticker)` | — |
| `save_fund_holdings`, `get_fund_holdings` | Multi-snapshot per `(fund_ticker, as_of_date)` | — |
| `get_sector_betas` / `save_sector_betas` | Long-format pairwise betas | — |

## Invariants you must respect

- **`cost_basis` is always per share.** `record_trade` does
  average-cost blending. CSV ingestion divides total cost by quantity.
  If you store total cost anywhere, you'll double-multiply later.
- **`save_portfolio` replaces positions entirely.** Treat it like PUT,
  not PATCH. The atomic upsert overwrites `created_at` on every save —
  this is why "list_portfolios newest-first" becomes "most recently
  edited first" in practice. Live with this until we add a separate
  `updated_at`.
- **Trade ledger is append-only.** Trades never get deleted. The
  positions table is *derived* from the ledger by `record_trade`'s
  applier — never edit positions directly when trades exist for the
  portfolio, or the next `AttributionEngine.refresh` (v2 trade replay)
  will overwrite them.

## Cash backfill quirk

`get_historical_prices(tickers)` returns a DataFrame with **all requested
tickers** as columns. When a ticker has no `prices/{TICKER}.parquet`:

- If *any* ticker has data → backfill the missing ticker with constant
  `1.0` aligned to the others' date index.
- If *all* tickers are missing and any of them is a Cash/CD ticker →
  synthesise a 252-day business-day index of `1.0`.
- Otherwise → a single row of `1.0` at today's date.

This is intentional — Cash and CDs are held at par, so `1.0` is correct
for them. The side effect is that *typos* in ticker names also become
`1.0`, which is documented in `services.schemas.price.LatestPriceResponse`.
If you need real "is this ticker known", call `get_all_tickers()`.

## Schema auto-migration

`_init_store()` checks each table for missing columns and backfills with
the defaults in `_MIGRATION_DEFAULTS`. Currently:

```python
{"income_rate": 0.0, "payment_frequency": 1}
```

Adding a new column is safe across versions — bump the dict if the
column needs a sensible default. **Removing or renaming a column
requires manual migration.**

## Things not in this layer

- CSV parsing — `src/data/ingestion.py`
- Risk/exposure/income computation — `src/reporting.py`
- Daily-metrics refresh — `src/attribution.py`
- Price collection from yfinance — `src/collector.py`
- Service-layer wrappers — `src/services/`

If you're tempted to add domain logic here, push it into one of those
modules instead and keep `Database` as the dumb-storage layer.

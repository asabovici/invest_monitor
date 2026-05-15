# Data Model

All state is stored as Parquet files under `data/` (gitignored). Demo mode uses an identical schema under `data_demo/`. Schema **auto-migrates** on `Database(...)` init — missing columns are backfilled with defaults from `_MIGRATION_DEFAULTS` (e.g. `income_rate=0.0`, `payment_frequency=1`).

## Parquet stores

| File | Schema |
|---|---|
| `assets.parquet` | `ticker, name, asset_type, currency, sector, income_rate, payment_frequency` |
| `portfolios.parquet` | `name, created_at` |
| `positions.parquet` | `portfolio_name, ticker, quantity, cost_basis` (per share) |
| `constituents.parquet` | `parent_ticker, constituent_ticker, weight` (legacy inline look-through) |
| `trades.parquet` | `trade_id, portfolio_name, ticker, side, quantity, trade_price, trade_date` |
| `fund_holdings.parquet` | `fund_ticker, as_of_date, holding_ticker, holding_name, weight, sector, asset_type` |
| `fund_profiles.parquet` | Long format: `fund_ticker, as_of_date, category, key, weight` |
| `sector_betas.parquet` | `sector_a, sector_b, beta, as_of_date` |
| `daily_security_metrics.parquet` | `date, ticker, price, daily_return, cum_return, rolling_vol_21d` |
| `daily_portfolio_metrics.parquet` | `date, portfolio_name, total_value, daily_return, cum_return, rolling_vol_21d, drawdown, max_drawdown` |
| `daily_attribution.parquet` | `date, portfolio_name, ticker, weight, position_return, contribution_to_return, asset_type, sector` |
| `production_jobs.parquet` | `job_name, enabled, interval_minutes, last_run_at, last_status, last_error, last_duration_seconds` |
| `production_runs.parquet` | `run_id, job_name, started_at, ended_at, status, error_message, details, duration_seconds` |
| `prices/<TICKER>.parquet` | `date` (index), `price` |

## Key concepts

### `cost_basis` is per-share

`positions.parquet.cost_basis` = cost **per share**, not total. `Portfolio.total_cost()` = `Σ(quantity × cost_basis)`. Storing total cost causes double-multiplication.

### `income_rate` has dual semantics

See [Income & SWR](income-and-swr.md):

| Asset type | Unit | Annual income |
|---|---|---|
| Stock / ETF / Fund | $ per share **per payment** | `quantity × income_rate × payment_frequency` |
| Bond / CD / Cash | annual **%** | `base_value × income_rate / 100` |

### Asset types

```python
class AssetType(Enum):
    STOCK  = "Stock"
    BOND   = "Bond"
    ETF    = "ETF"
    FUND   = "Fund"
    CASH   = "Cash"
    CD     = "CD"
    CRYPTO = "Crypto"
```

`Cash` and `CD` get a synthetic constant-1.0 daily price series automatically — risk metrics still compute (vol = 0, drawdown = 0) without requiring real prices.

!!! warning "Streamlit hot-reload + enum comparison"
    Streamlit can re-import `AssetType` under a different class identity. Comparisons like `pos.asset.asset_type in (AssetType.ETF, AssetType.FUND)` will then return `False` for genuine ETF positions. **Always compare on `.value`** instead: `pos.asset.asset_type.value in ("ETF", "Fund")`. All codebase comparisons are now done this way; new code should follow suit.

## Domain model

```
Portfolio
  └── List[Position]
        ├── asset: Asset
        │     ├── ticker, name, asset_type, currency, sector
        │     ├── income_rate          # $/share/pmt (equity) or %/yr (income)
        │     ├── payment_frequency    # 1 | 2 | 4 | 12
        │     └── constituents: List[Constituent]   # legacy ETF look-through
        ├── quantity: float
        └── cost_basis: float          # ALWAYS per share
```

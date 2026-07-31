# Ingestion

A single module — `ingestion.py` — that parses two flavours of CSV into
the parquet store:

1. **Portfolio holdings** (`Ingester.load_portfolio_from_csv`)
2. **ETF / fund holdings** (`Ingester.parse_fund_holdings_csv`)

Not to be confused with `src/database/`, which owns the *storage* layer.
Ingestion is the "from a file outside our system into our schema" layer.

## Portfolio holdings CSV

Expected columns:

| Column | Required | Notes |
|---|---|---|
| `Ticker` | yes | |
| `Name` | yes | Asset display name |
| `Type` | yes | One of `Stock` / `Bond` / `ETF` / `Fund` / `Cash` / `CD` / `Crypto` (must parse via `AssetType(value)`) |
| `Quantity` | yes | Number of shares (or par value for bonds) |
| `CostBasis` | yes | **Total** cost. Divided by `Quantity` on the way in to store per-share. |
| `Currency` | optional | Defaults to `USD` |
| `Sector` | optional | Free text; canonical keys live in `src.scenarios.SECTOR_KEYS` |
| `ConstituentTickers` | optional | Comma-separated for composite (lookthrough) assets |
| `ConstituentWeights` | optional | Comma-separated weights aligned with above |

Each row triggers `db.add_asset(...)` (idempotent upsert into
`assets.parquet`) followed by appending a `Position` to the in-memory
`Portfolio`. The final `db.save_portfolio(portfolio)` replaces the
positions for that name atomically.

Both the dashboard's CSV upload (Streamlit) and `invest-monitor load <csv>`
now go through `services.portfolios.load_portfolio_from_csv`, which is a
thin wrapper around this code that takes the CSV as a text blob (or
upload bytes). Direct callers should prefer the service.

## ETF / fund holdings CSV

`parse_fund_holdings_csv(content: bytes, fund_ticker: str)` returns a
normalised DataFrame with columns
`holding_ticker, holding_name, weight, sector, asset_type`.

Auto-detects three vendor layouts:

- **iShares**: skips ~9 header rows, looks for `Ticker`, `Name`,
  `Weight (%)`, `Sector`, `Asset Class`.
- **Vanguard**: `Holdings`, `Shares`, `% of fund`, `Sector`.
- **Generic**: any CSV with a weight-like column + a name/ticker column.

The fund-holdings table is keyed `(fund_ticker, as_of_date)`, so monthly
snapshots stack — useful for the Lookthrough tab's history view.

## Conventions

- `CostBasis` in the input is total; storage is per-share. Don't change
  the divide-on-import behavior without auditing every downstream
  weight / income calculation.
- Composite (lookthrough) assets are stored via `constituents.parquet` —
  see `src/database/CLAUDE.md` for that side. Ingestion just writes the
  row; the join happens at read time.
- Sector values can be free-text; canonical normalisation lives in
  `src.scenarios:normalize_sector`. Stress tests run that on every
  sector string before lookup.

## Where this hands off

```
Ingester.load_portfolio_from_csv()
  → Database.add_asset()  (upsert assets.parquet)
  → Database.save_portfolio(Portfolio(name, positions))
                          (upsert portfolios + replace positions)
```

After ingestion, the new tickers usually have no price history yet —
prompt the user (or kick off a job) to run
`invest-monitor collect --portfolio <name>` so reports work.

# ETF / Fund Lookthrough

Two ways to teach the app what an ETF / Fund holds:

=== "Vendor holdings CSV (ticker-level)"

    Upload a monthly holdings file from your ETF vendor (iShares, Vanguard, etc.) in the **🔍 Lookthrough** tab. The parser auto-detects common layouts (skips vendor metadata header rows) and fuzzy-matches columns for ticker, name, weight, sector, and asset class.

    Both `7.0`-style percentages and `0.07`-style fractions are accepted — detected by whether the column sums to > 1.5. Result lands in `fund_holdings.parquet` keyed on `(fund_ticker, as_of_date)`.

    **Fidelity:** ticker-level. AAPL via VTI shows up as a real AAPL row.

=== "yfinance fund profile (sector-level)"

    Click **Fetch Profile from yfinance** in the same tab. This pulls `asset_classes` (stock / bond / cash / preferred / convertible / other position weights) and `sector_weightings` from `yfinance.Ticker(ticker).funds_data`.

    Result lands in `fund_profiles.parquet`. **Fidelity:** sector-level — synthetic rows like `"VTI → Technology"`, `"VTI → Bond"`, `"VTI → Cash"`. No individual constituent tickers.

## Resolution order

`expand_lookthrough_rows` picks the highest-fidelity source available per fund:

| Priority | Source | Tag in `Source` column | Fidelity |
|---|---|---|---|
| 1 | `fund_holdings.parquet` | `vendor`   | Ticker-level: each constituent becomes a row keyed on its real ticker |
| 2 | `fund_profiles.parquet` | `yfinance` | Sector-level: equity portion spread across `sector_weightings`; bond / cash portions emit their own rows |
| 3 | (none)                  | `native`   | Kept as a single opaque fund row |

The **🔍 Apply ETF / Fund lookthrough** toggle appears in three views (each with its own default):

| View | Default |
|---|---|
| Single Portfolio → 📊 Overview | OFF |
| Single Portfolio → 🥧 Exposure | ON  |
| Multi-Portfolio Dashboard → Aggregate Exposure | OFF |

When the toggle is on, the tooltip lists which funds use vendor data vs which fall back to yfinance.

## Invariance

Dollar totals (Current Value, Total Cost, P&L) are **invariant** under lookthrough — they're redistributed across constituent rows, not re-valued. Share-level fields (Quantity, Cost Basis, Current Price) are `None` on synthetic rows since those don't apply to apportioned slices.

## Edge cases

- **Inverse / leveraged ETFs** (e.g. SH with `stockPosition = -1.0`, `cashPosition = 1.82`): negative weights are clipped to 0 and the remaining components renormalised so they sum to 1. The "short equity" signal is lost, but total dollar value is preserved. SH looks through to ~100% Cash (its actual collateral composition), not negative equity.
- **Commodities ETFs** (e.g. PDBC, GLDM with `otherPosition` and no sector_weightings): the equity-like portion is bucketed as `Stock / Unknown`. Override the asset_type in Security Master if you want to track them as Commodity.
- **Asset-class data missing**: if a fund has no asset_classes at all (only sector_weightings), the equity portion is treated as 100%. If neither is present, the helper falls through to the native opaque row.

## Multi-Portfolio Top-15 underlying exposures

With lookthrough on, the **Top 15 underlying exposures** table on the Multi-Portfolio Dashboard surfaces *cross-fund concentration*. If you hold AAPL via VTI **and** VOO **and** IWF, the lookthrough rows aggregate to a single AAPL row with `Held Via: VTI, VOO, IWF` — so you can see the true single-name exposure rather than three separate ETF lines.

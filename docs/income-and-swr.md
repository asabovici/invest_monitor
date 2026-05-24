# Income & Safe Withdrawal Rate

Two related features for understanding *cash flow* in your portfolio:

- **Income Projection** — annual cash flow your portfolio generates from coupons (Bond/CD), interest (Cash), and dividends (Stock/ETF/Fund).
- **Safe Withdrawal Rate (SWR)** — Bengen-style cash flow flowing *out* of the portfolio in retirement.

## Income Rate semantics

`income_rate` and `payment_frequency` on each asset capture recurring cash flows. **Units of `income_rate` depend on `asset_type`:**

| Asset type | `income_rate` unit | Annual income |
|---|---|---|
| Stock / ETF / Fund | **$ per share per payment** | `quantity × income_rate × payment_frequency` |
| Bond / CD | annual **%** (coupon) | `base_value × income_rate / 100` |
| Cash | annual **%** (yield) | `base_value × income_rate / 100` |

!!! example "BLK example"
    BLK pays a $5.72 quarterly dividend.

    Set `income_rate = 5.72`, `payment_frequency = 4` in the Security Master.

    Annual = `quantity × 5.72 × 4`.

The 12-month payment schedule chart in the Income tab respects `payment_frequency`: a monthly bond shows 12 payments, a semi-annual bond shows 2, etc. Income contributions also lift each ticker's daily return inside `compute_portfolio_metrics`, so 1M / 3M / 6M / 1Y horizon returns include yield.

## Income Projection

Per-portfolio (Single Portfolio → **💵 Income** tab) and aggregate (Multi-Portfolio Dashboard → **Income Projection** section):

- KPIs: Annual Income / Monthly Average / Portfolio Yield / Income-Generating positions.
- Donut by asset type (excludes zero-income positions).
- 12-month calendar schedule chart.
- Per-position detail table with raw `Income Rate`, `Annual Income`, `Monthly Income`, `Yield on Base (%)`.

## Safe Withdrawal Rate (SWR)

The Wealth Projection section's **💰 Withdrawals (Safe Withdrawal Rate)** expander applies to both Deterministic and Monte Carlo methods. Inspired by Bengen's 4% rule and the Trinity Study.

### Settings

| Field | Meaning |
|---|---|
| **Apply annual withdrawals** | Master on/off. When off, projection runs no-withdrawal as before. |
| **Primary withdrawal rate (%)** | Default 4.0%. Dollar amount = `swr% × today's portfolio value`, grown by inflation each year. |
| **Inflation adjustment (%/yr)** | Default 3.0%. Set to 0 for nominal-flat withdrawals. |
| **Rebalance to starting weights each year** | Default ON. Snap each position back to its starting weight × current total after returns + withdrawal. |
| **Compare additional rates** (MC only) | Multi-select. Same return paths (RNG seed unchanged) re-used; only the withdrawal arithmetic changes. |

### Year-by-year mechanics

```
target_weights[i] = pos_i.start_value / portfolio.start_value    # captured at year 0
base_withdrawal   = portfolio.start_value × (primary_swr_pct / 100)

for yr in 1..horizon:
    # 1) Apply asset-type returns independently.
    pos_values *= (1 + return_for_year)
    pos_values  = max(0, pos_values)

    # 2) Subtract pro-rata withdrawal (Bengen-style fixed-real-dollar).
    wd_this_year = base_withdrawal × (1 + inflation_pct/100) ^ (yr-1)
    actual       = min(wd_this_year, total)
    pos_values  *= (total - actual) / total

    # 3) Optional rebalance to starting weights.
    if rebalance_annually:
        pos_values = total_after_wd × target_weights
```

### Outputs

**Deterministic**
- Chart title gains the withdrawal annotation.
- Milestone table gets a **Depletes** column: `Year N` if the portfolio hits zero, else `—`.

**Monte Carlo**
- KPI strip expands to 5 columns: P50 / P25 / P75 / **Survival @ primary SWR%** / **Median depletion year**.
- New **Survival across withdrawal rates** table when the compare list is non-empty. One row per rate with Survival %, P10/P50/P90 terminal value, and median depletion year.

### Reading the comparison table

Look for the highest SWR whose Survival meets your target threshold (commonly 90–95% for conservative retirement planning). Combine with the regime presets in [Wealth Projection](wealth-projection.md) to gauge sensitivity — a 4% SWR that survives 95% of the time under the 2010s Recovery regime may only survive 70% under 2000s Dual Shock.

### Rebalancing impact

Rebalancing modestly improves survival under SWR — at 4% over 30y on a 60/40 portfolio, survival ticks up from ~71% (drift) to ~75% (rebalance), and P10 terminal value roughly doubles. The mechanism: trim positions that overshot, top up those that lagged.

# Risk Analytics

The Single Portfolio **⚠️ Risk** tab covers measurement + scenario stress testing.

## Standard metrics

- **Annualised volatility** — `σ_daily × √252`.
- **Historical VaR (95%)** — 5th percentile of observed daily returns.
- **Monte Carlo VaR (95%)** — parametric: 10,000 draws from `N(mean, std)`, take the 5th percentile.
- **Covariance matrix** — annualised pairwise covariances, rendered as a Plotly heatmap.
- **Correlation heatmap** — pairwise return correlations across all positions.
- **Portfolio return distribution** — histogram of daily returns with VaR line.

## Sector Stress Test

The Risk tab's stress test has three modes via the Scenario selector:

=== "Custom"

    All sectors and non-equity asset types start at 0%. Edit any cell in the **Edit shocks** expander.

=== "Implied (beta from driver sector)"

    Pick a driver sector + a shock %, and every other sector's implied shock is derived from a pairwise OLS beta matrix computed from SPDR sector ETFs.

    ```
    implied_shock(sector) = β(sector, driver) × driver_shock
    ```

    First-time setup: click **Refresh betas** to fetch 20 years of SPDR sector ETF prices (XLK, XLV, XLF, XLY, XLP, XLC, XLI, XLE, XLU, XLB, XLRE) and compute the matrix. Result lands in `sector_betas.parquet`.

    For each sector pair, betas are computed on the overlap of available data — so short-history ETFs (XLC since 2018, XLRE since 2015) still get an honest beta on their available window.

=== "Named historical scenarios"

    Seven presets pre-filled with sector-level shock recipes:
    
    - 2008 Financial Crisis
    - Dot-Com Crash (Tech)
    - Rate Hike (2022-style)
    - Energy Shock (Oil +50%)
    - Mild Correction (-10%)
    - Severe Drawdown (-30%)
    - Bull Run (+15%)

### Per-position application

For each position, `compute_sector_stress`:

| Asset type | Shock derivation |
|---|---|
| **Stock** | `sector_shocks[normalize_sector(asset.sector)]`. Falls back to average sector shock if the sector is unrecognised. |
| **ETF / Fund** | Splits the position by `asset_classes` (stockPosition / bondPosition / cashPosition) and shocks the **equity portion** by the weighted blend of `sector_weightings × sector_shocks` (renormalised). Bond portion shocked by `non_equity_shocks["Bond"]`. Cash by 0. |
| **Bond / Cash / CD / Crypto** | Direct: `non_equity_shocks[asset_type]`. |

ETFs without a fund profile fall back to "average sector shock" with a clearly-labeled source.

### Outputs

- KPI strip: Base Value / Stressed Value (with delta) / Total Change.
- Per-position stress table: Ticker, Type, Base Value, Shock %, New Value, Change $, Source.
- Horizontal bar chart of stressed P&L sorted by impact.

## Cross-asset beta table

For higher-level stress modelling (used by the WealthAgent's `run_scenario_analysis` skill):

| Asset class | Beta vs equities |
|---|---|
| Stock | 1.00 |
| ETF | 0.85 |
| Fund | 0.70 |
| Bond | −0.15 |
| Crypto | 0.75 |
| Cash | 0.00 |
| CD | 0.00 |

When you shock one asset class, implied shocks for the rest are computed as `beta × shocked_return`.

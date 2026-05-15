# Wealth Projection

The Multi-Portfolio Dashboard's **Wealth Projection** section supports two methods plus an optional [Safe Withdrawal Rate](income-and-swr.md) layer.

## Method: Deterministic

Fixed expected return per asset type, with 1–3 contiguous time periods. Each period assigns its own per-type return; the simulation compounds positions year by year using those rates. Optional growth-period splits let you model e.g. "high returns next 5 years, lower returns after".

Asset types: `Stock`, `ETF`, `Bond`, `Fund`, `Cash`, `CD`.

Output: one line per portfolio + dashed TOTAL line (when 2+ portfolios), plus a milestone table at years 5/10/15/20/30/40/50 (capped by horizon).

## Method: Monte Carlo

Vectorised draws from `multivariate_normal(μ, Σ)` per asset-type per simulation per year. Inputs:

| Field | Default |
|---|---|
| Projection horizon (years) | 20 |
| Number of simulations | 2,000 (up to 10k) |
| Goal amount (optional, $) | 0 |
| **Expected Return (μ)** per asset type | Stock 8%, ETF 7%, Bond 3.5%, Fund 6%, Cash 4.5%, CD 4.5% |
| **Volatility (σ)** per asset type | Stock 18%, ETF 14%, Bond 5%, Fund 11%, Cash 0.5%, CD 0% |
| **Cross-asset correlations** | Editable 6×6 matrix; default Stock/Bond = −0.10, Stock/Fund = 0.70, Cash/CD = 0.60 |

The covariance matrix is built as `Σ = ρ ⊙ σσᵀ`. User edits to the correlation matrix are auto-symmetrised (`(M + Mᵀ)/2`) and the diagonal is forced to 1. A PSD safety-net eigendecomposes and floors any negative eigenvalues to `1e-10` so even a wildly invalid edit produces a usable matrix.

### Outputs

- **Fan chart** with shaded P10–P90 outer band, darker P25–P75 inner band, solid median.
- **KPI strip**: P50 / P25 / P75 / Expected (mean) — or P(reach goal) if a goal is set.
- **Milestone percentile table** at years 5/10/15/20/30/40/50.
- **Per-portfolio outcome table** at the end of the horizon.

## Historical regime presets

Picking a preset re-seeds the return / vol / correlation inputs from that period's stats:

| Preset | Stock μ | Stock σ | Bond μ | ρ(Stk, Bnd) | Story |
|---|---|---|---|---|---|
| **1970s Stagflation** | 5.9% | 16% | 3.5% | **+0.30** | Inflation hurts both stocks and bonds |
| **1980s Bull Run** | 17.6% | 16% | 13.1% | +0.20 | Volcker disinflation rally |
| **1990s Japan Deflation** | **−7%** | 22% | 5% | **−0.40** | Bonds were the only hedge |
| **2000s Dual Shock** | −1% | 21% | 6.5% | −0.30 | Lost decade for equities |
| **2010s Recovery** | 13.5% | 13% | 3.5% | −0.30 | Textbook 60/40 era |
| **2020s Rate-Hike Era** | 10% | 18% | **−1%** | **+0.40** | Diversification broke down |

!!! tip "Stock/Bond correlation flip"
    The flip between the 2010s (−0.30) and 2020s (+0.40) is the most useful comparison — you'll see how dramatically a 60/40 portfolio's fan widens when its diversification benefit disappears.

## Safe Withdrawal Rate layer

Optional withdrawals applied year-by-year. Full details on [Income & SWR](income-and-swr.md). Highlights:

- Bengen-style fixed-real-dollar withdrawal, optional inflation adjustment.
- Pro-rata subtraction across positions, clipped at zero.
- Optional annual rebalance to starting weights (default ON when SWR is enabled).
- MC mode supports a **Survival across withdrawal rates** comparison table — same return paths, different SWRs, so you can find the highest rate meeting your target threshold.

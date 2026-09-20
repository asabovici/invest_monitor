/** Typed client for the invest-monitor HTTP API.
 *
 *  Paths are relative so Vite's dev proxy (and any reverse proxy in front of
 *  a built bundle) sees a single origin — no CORS config needed on the
 *  Python side.
 */

export interface Holding {
  ticker: string
  /** Display name from the security master; falls back to the ticker. */
  name: string
  account: string
  asset_type: string
  quantity: number
  price: number
  market_value: number
  cost: number
}

export interface ValueSeries {
  dates: string[]
  total: number[]
  /** Keyed by asset type, aligned index-for-index with `dates`. */
  by_type: Record<string, number[]>
}

export interface DashboardSnapshot {
  market_value: number
  cost: number
  gain: number
  /** Fixed stacking + colour order. Never re-sort this. */
  asset_type_order: string[]
  totals_by_type: Record<string, number>
  totals_by_account: Record<string, number>
  series: ValueSeries
  holdings: Holding[]
  /** Tickers with no usable price; excluded from every total. */
  unpriced: string[]
}

export class ApiError extends Error {
  // Declared explicitly rather than as a constructor parameter property,
  // which `erasableSyntaxOnly` disallows.
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function get<T>(path: string, dataDir?: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      headers: dataDir ? { 'X-Data-Dir': dataDir } : {},
    })
  } catch {
    // fetch only rejects on a transport failure — almost always "API isn't running".
    throw new ApiError(0, 'Could not reach the API.')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const fetchDashboard = (dataDir?: string) =>
  get<DashboardSnapshot>('/dashboard', dataDir)

export interface Slice { label: string; value: number; weight: number }
export interface Contributor { ticker: string; name: string; value: number }
export interface Breakdown {
  slices: Slice[]
  base: number
  covered: number
  unclassified: number
  top_contributors: Record<string, Contributor[]>
}
export interface ExposureReport {
  market_value: number
  by_asset_class: Breakdown
  by_sector: Breakdown
  /** Inverse-fund equity, as a positive number; not allocatable to sectors. */
  short_equity: number
  as_of: string
  unprofiled_funds: string[]
  renormalised_funds: string[]
}

export const fetchExposure = (dataDir?: string) =>
  get<ExposureReport>('/exposure', dataDir)

export interface RiskMetrics {
  annualised_volatility: number
  historical_var_95: number
  monte_carlo_var_95: number
  max_drawdown: number
  best_day: number
  worst_day: number
  observations: number
}
export interface ProjectionBands {
  dates: string[]
  p5: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[]
}
export interface Projection {
  years: number
  num_simulations: number
  monthly_contribution: number
  total_contributions: number
  goal_amount: number | null
  probability_of_success: number | null
  expected_value: number
  final_percentiles: Record<string, number>
  bands: ProjectionBands
  assumed_annual_return: number
  assumed_annual_volatility: number
}
export interface RiskReport {
  market_value: number
  metrics: RiskMetrics
  projection: Projection
  holdings_covered: number
  holdings_total: number
  /** Suspect price points excluded from the fit. */
  data_notes: string[]
}

export const fetchRisk = (params: {
  dataDir?: string; years: number; goal?: number; monthly: number
}) => {
  const q = new URLSearchParams({
    years: String(params.years),
    monthly_contribution: String(params.monthly),
  })
  if (params.goal) q.set('goal_amount', String(params.goal))
  return get<RiskReport>(`/risk?${q}`, params.dataDir)
}

export interface IncomeHolding {
  ticker: string; name: string; account: string; asset_type: string
  market_value: number; annual_income: number; monthly_income: number
  yield_pct: number; payment_frequency: number
}
export interface IncomeBucket {
  label: string; annual_income: number; market_value: number; yield_pct: number
}
export interface IncomeReport {
  market_value: number
  annual_income: number
  monthly_income: number
  portfolio_yield_pct: number
  by_asset_type: IncomeBucket[]
  by_account: IncomeBucket[]
  holdings: IncomeHolding[]
  non_income_value: number
  non_income_tickers: string[]
}

export const fetchIncome = (dataDir?: string) => get<IncomeReport>('/income', dataDir)

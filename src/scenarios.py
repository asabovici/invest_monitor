"""Scenario definitions and cross-asset beta table for scenario-based projections.

A Scenario is composed of one or more ScenarioPhases.  Each phase covers a
contiguous block of trading days and carries multipliers that modify the
portfolio's historical daily return (mu) and volatility (sigma), plus an
optional one-time fractional shock applied on the first day of that phase.

Cross-asset betas capture the sensitivity of each asset class to a unit move
in equities (Stock).  They are used to imply shocks to the rest of the
portfolio when the user shocks only one asset class.
"""

from dataclasses import dataclass, field
from typing import List

# Sentinel value: phase runs until the end of the simulation horizon.
_INF_DAYS = 10_000_000


@dataclass
class ScenarioPhase:
    """A single time slice within a scenario.

    Attributes:
        name: Human-readable label for this phase.
        duration_days: Trading days this phase lasts.  Use _INF_DAYS for
            "remainder of horizon".
        return_multiplier: Multiplicative factor applied to the portfolio's
            historical daily mu.  Negative values flip the sign of mu (e.g.,
            -2.0 doubles the magnitude but makes positive historical mu negative).
        vol_multiplier: Multiplicative factor applied to historical daily sigma.
        one_time_shock: Fractional shock applied to portfolio value at the very
            first day of this phase (e.g., -0.15 means an immediate -15% hit).
    """

    name: str
    duration_days: int
    return_multiplier: float = 1.0
    vol_multiplier: float = 1.0
    one_time_shock: float = 0.0


@dataclass
class Scenario:
    name: str
    description: str
    phases: List[ScenarioPhase] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pre-built scenarios
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, Scenario] = {
    "base": Scenario(
        name="base",
        description=(
            "Historical average returns and volatility — no adjustments. "
            "Equivalent to the standard Monte Carlo projection."
        ),
        phases=[ScenarioPhase("base", _INF_DAYS)],
    ),
    "market_crash": Scenario(
        name="market_crash",
        description=(
            "Severe 2008-style crash: sharp immediate drop (~15%), prolonged bear "
            "market, then a slow multi-year recovery at modestly above-average returns."
        ),
        phases=[
            # ~3 months of intense selling; one-time 15% drop on day 1
            ScenarioPhase("crash",       63,        -8.0, 3.5, -0.15),
            # ~12 months grinding lower / sideways
            ScenarioPhase("bear_market", 252,       -2.0, 2.0,  0.00),
            # recovery — slightly above historical average, elevated vol
            ScenarioPhase("recovery",    _INF_DAYS,  1.2, 1.2,  0.00),
        ],
    ),
    "mild_correction": Scenario(
        name="mild_correction",
        description=(
            "10–15% correction over ~3 months (common in healthy bull markets), "
            "followed by a full rebound to above-average returns."
        ),
        phases=[
            ScenarioPhase("correction", 63,        -3.0, 2.0, -0.05),
            ScenarioPhase("rebound",    _INF_DAYS,  1.1, 1.0,  0.00),
        ],
    ),
    "prolonged_low_growth": Scenario(
        name="prolonged_low_growth",
        description=(
            "A 'lost decade' style environment: returns compressed to ~20% of "
            "historical average for the entire horizon.  Models secular stagnation "
            "or Japan-style deflation."
        ),
        phases=[
            ScenarioPhase("stagnation", _INF_DAYS, 0.2, 0.8),
        ],
    ),
    "stagflation": Scenario(
        name="stagflation",
        description=(
            "1970s-style stagflation: equities flat to mildly negative in real "
            "terms, elevated volatility, bonds also suffer from rising rates."
        ),
        phases=[
            ScenarioPhase("stagflation", _INF_DAYS, -0.3, 1.5),
        ],
    ),
    "bull_run": Scenario(
        name="bull_run",
        description=(
            "Strong secular bull market: returns roughly doubled relative to "
            "historical average, volatility compressed (low-fear environment)."
        ),
        phases=[
            ScenarioPhase("bull", _INF_DAYS, 2.0, 0.7),
        ],
    ),
    "flash_crash_recovery": Scenario(
        name="flash_crash_recovery",
        description=(
            "Sudden ~12% flash crash (1 month), followed by a rapid V-shaped "
            "recovery at double the historical average return."
        ),
        phases=[
            ScenarioPhase("crash",    21,        -10.0, 4.0, -0.12),
            ScenarioPhase("recovery", _INF_DAYS,   2.0, 1.5,  0.00),
        ],
    ),
    "double_dip": Scenario(
        name="double_dip",
        description=(
            "Two distinct downturns separated by a false recovery: a bear market, "
            "a brief bounce, then a second leg down, followed by genuine recovery."
        ),
        phases=[
            ScenarioPhase("first_bear",       126, -4.0, 2.5, -0.10),
            ScenarioPhase("false_recovery",    63,  1.5, 1.5,  0.00),
            ScenarioPhase("second_bear",      126, -3.0, 2.0, -0.08),
            ScenarioPhase("recovery",    _INF_DAYS,  1.3, 1.1,  0.00),
        ],
    ),
    "rate_shock": Scenario(
        name="rate_shock",
        description=(
            "Sudden interest-rate spike (2022-style): equities fall 20–30%, bonds "
            "suffer simultaneously, then markets stabilise at lower valuations."
        ),
        phases=[
            ScenarioPhase("shock",       126, -5.0, 2.0, -0.10),
            ScenarioPhase("adjustment",  252,  0.1, 1.3,  0.00),
            ScenarioPhase("new_normal",  _INF_DAYS, 0.8, 1.0, 0.00),
        ],
    ),
}

# ---------------------------------------------------------------------------
# Cross-asset beta table
# ---------------------------------------------------------------------------

# Each value is the sensitivity (beta) of that asset class to a 1-unit move
# in equities (Stock).  A negative beta means the asset typically moves
# *opposite* to equities (e.g., government bonds rallying during a crash).
#
# Source: broad empirical estimates from academic literature and practitioner
# research (Asness et al., Ilmanen).  These are reasonable starting points —
# individual portfolio constituents will differ.
CROSS_ASSET_BETAS: dict[str, float] = {
    "Stock":  1.00,   # equities are the reference
    "ETF":    0.85,   # broad equity ETFs track equities closely
    "Fund":   0.70,   # mutual funds; may include fixed-income components
    "Bond":  -0.15,   # flight-to-quality; gov bonds often rally in crashes
    "Crypto": 0.75,   # high beta to equities in risk-off moves
    "Cash":   0.00,   # no sensitivity
    "CD":     0.00,   # held to maturity at constant principal; no market beta
}

# Cross-asset-class correlations used to draw correlated annual returns in the
# Monte Carlo wealth projection. Symmetric, 1s on the diagonal. Empirical
# starting points — broad equity / bond / cash relationships are well-known;
# CDs track cash but with slightly higher rate sensitivity.
WEALTH_MC_ASSET_TYPES: list[str] = ["Stock", "ETF", "Bond", "Fund", "Cash", "CD"]

DEFAULT_ASSET_CORRELATIONS: dict[str, dict[str, float]] = {
    "Stock": {"Stock": 1.00, "ETF":  0.85, "Bond": -0.10, "Fund":  0.70, "Cash": 0.00, "CD": 0.00},
    "ETF":   {"Stock": 0.85, "ETF":  1.00, "Bond": -0.05, "Fund":  0.75, "Cash": 0.00, "CD": 0.00},
    "Bond":  {"Stock":-0.10, "ETF": -0.05, "Bond":  1.00, "Fund":  0.30, "Cash": 0.10, "CD": 0.20},
    "Fund":  {"Stock": 0.70, "ETF":  0.75, "Bond":  0.30, "Fund":  1.00, "Cash": 0.00, "CD": 0.00},
    "Cash":  {"Stock": 0.00, "ETF":  0.00, "Bond":  0.10, "Fund":  0.00, "Cash": 1.00, "CD": 0.60},
    "CD":    {"Stock": 0.00, "ETF":  0.00, "Bond":  0.20, "Fund":  0.00, "Cash": 0.60, "CD": 1.00},
}


def _corr_from_defaults(
    stock_bond: float = -0.10,
    etf_bond:   float = -0.05,
    cash_bond:  float =  0.10,
    cd_bond:    float =  0.20,
    cash_cd:    float =  0.60,
    extras:     dict[tuple[str, str], float] | None = None,
) -> dict[str, dict[str, float]]:
    """Build a full correlation matrix by overriding key cross-pairs on
    DEFAULT_ASSET_CORRELATIONS. The Stock↔Bond pair is the dominant lever
    historically — that's why it's the headline argument."""
    m = {a: dict(row) for a, row in DEFAULT_ASSET_CORRELATIONS.items()}

    def _set(a, b, v):
        m[a][b] = m[b][a] = v

    _set("Stock", "Bond", stock_bond)
    _set("ETF",   "Bond", etf_bond)
    _set("Cash",  "Bond", cash_bond)
    _set("CD",    "Bond", cd_bond)
    _set("Cash",  "CD",   cash_cd)
    for (a, b), v in (extras or {}).items():
        _set(a, b, v)
    return m


# Historical regime presets for the Monte Carlo wealth projection.
# Numbers are nominal USD-equivalent annualised return / vol approximations
# drawn from period-specific equity / bond / T-bill stats (Ibbotson, Bloomberg,
# Aswath Damodaran's historical data). Tweak after loading if you have a
# different reference set in mind.
WEALTH_MC_PRESETS: dict[str, dict] = {
    "1970s Stagflation": {
        "description": (
            "US 1970–1979. High inflation, equities flat in real terms, "
            "rising rates hurt bonds. Stock↔Bond correlation positive — "
            "both assets sold off together on inflation surprises."
        ),
        "returns": {"Stock":  5.9, "ETF":  5.5, "Bond":  3.5, "Fund":  5.0, "Cash": 6.3, "CD": 6.5},
        "vols":    {"Stock": 16.0, "ETF": 14.0, "Bond":  7.0, "Fund": 12.0, "Cash": 1.5, "CD": 0.5},
        "correlations": _corr_from_defaults(
            stock_bond=0.30, etf_bond=0.25, cash_bond=0.30, cd_bond=0.30, cash_cd=0.85,
        ),
    },
    "1980s Bull Run": {
        "description": (
            "US 1980–1989. Post-Volcker disinflation: rates fell from peak, "
            "equities re-rated higher. Both stocks and bonds rallied — "
            "positive correlation, low to moderate vol."
        ),
        "returns": {"Stock": 17.6, "ETF": 16.0, "Bond": 13.1, "Fund": 14.0, "Cash": 8.0, "CD": 8.5},
        "vols":    {"Stock": 16.0, "ETF": 14.0, "Bond": 10.0, "Fund": 12.0, "Cash": 1.5, "CD": 1.0},
        "correlations": _corr_from_defaults(
            stock_bond=0.20, etf_bond=0.20, cash_bond=0.25, cd_bond=0.30, cash_cd=0.85,
        ),
    },
    "1990s Japan Deflation": {
        "description": (
            "Japan 1990–1999 'Lost Decade'. Nikkei fell ~7%/yr nominal, "
            "JGBs rallied as rates collapsed toward zero. Strong negative "
            "Stock↔Bond correlation — bonds were the hedge."
        ),
        "returns": {"Stock": -7.0, "ETF": -5.0, "Bond":  5.0, "Fund": -3.0, "Cash": 1.0, "CD": 1.2},
        "vols":    {"Stock": 22.0, "ETF": 18.0, "Bond":  5.0, "Fund": 14.0, "Cash": 0.3, "CD": 0.2},
        "correlations": _corr_from_defaults(
            stock_bond=-0.40, etf_bond=-0.30, cash_bond=0.05, cd_bond=0.10, cash_cd=0.70,
        ),
    },
    "2000s Dual Shock": {
        "description": (
            "US 2000–2009. Dot-com bust + Global Financial Crisis. S&P 500 "
            "lost money over the decade while long Treasuries rallied as "
            "rates fell. Strongly negative Stock↔Bond correlation."
        ),
        "returns": {"Stock": -1.0, "ETF":  0.5, "Bond":  6.5, "Fund":  2.5, "Cash": 2.7, "CD": 3.0},
        "vols":    {"Stock": 21.0, "ETF": 17.0, "Bond":  5.0, "Fund": 13.0, "Cash": 0.5, "CD": 0.2},
        "correlations": _corr_from_defaults(
            stock_bond=-0.30, etf_bond=-0.25, cash_bond=0.15, cd_bond=0.20, cash_cd=0.65,
        ),
    },
    "2010s Recovery": {
        "description": (
            "US 2010–2019. Strong secular equity bull driven by QE and low "
            "rates. Bond returns muted, vol suppressed. Textbook negative "
            "Stock↔Bond correlation — the classic 60/40 era."
        ),
        "returns": {"Stock": 13.5, "ETF": 12.0, "Bond":  3.5, "Fund":  9.0, "Cash": 0.6, "CD": 1.0},
        "vols":    {"Stock": 13.0, "ETF": 11.0, "Bond":  3.0, "Fund":  9.0, "Cash": 0.2, "CD": 0.1},
        "correlations": _corr_from_defaults(
            stock_bond=-0.30, etf_bond=-0.25, cash_bond=0.05, cd_bond=0.10, cash_cd=0.50,
        ),
    },
    "2020s Rate-Hike Era": {
        "description": (
            "US 2020–2024. COVID volatility then the fastest Fed hiking "
            "cycle in 40 years. Bonds had their worst year in 2022; "
            "Stock↔Bond correlation flipped positive — diversification "
            "broke down when both assets were hurt by rising rates."
        ),
        "returns": {"Stock": 10.0, "ETF":  9.0, "Bond": -1.0, "Fund":  6.0, "Cash": 2.5, "CD": 3.5},
        "vols":    {"Stock": 18.0, "ETF": 15.0, "Bond":  7.0, "Fund": 12.0, "Cash": 0.8, "CD": 0.3},
        "correlations": _corr_from_defaults(
            stock_bond=0.40, etf_bond=0.35, cash_bond=0.25, cd_bond=0.30, cash_cd=0.75,
        ),
    },
}

# ---------------------------------------------------------------------------
# Sector-level stress scenarios (one-shot, instantaneous shocks)
# ---------------------------------------------------------------------------

# Canonical sector keys — match yfinance funds_data.sector_weightings keys.
SECTOR_KEYS: list[str] = [
    "technology", "healthcare", "financial_services", "consumer_cyclical",
    "consumer_defensive", "communication_services", "industrials", "energy",
    "utilities", "basic_materials", "realestate",
]

# SPDR Select Sector ETFs — the public proxies we use to estimate sector
# returns when computing pairwise betas.
SECTOR_ETF_TICKERS: dict[str, str] = {
    "technology":             "XLK",
    "healthcare":             "XLV",
    "financial_services":     "XLF",
    "consumer_cyclical":      "XLY",
    "consumer_defensive":     "XLP",
    "communication_services": "XLC",
    "industrials":            "XLI",
    "energy":                 "XLE",
    "utilities":              "XLU",
    "basic_materials":        "XLB",
    "realestate":             "XLRE",
}

SECTOR_DISPLAY: dict[str, str] = {
    "technology":             "Technology",
    "healthcare":             "Healthcare",
    "financial_services":     "Financial Services",
    "consumer_cyclical":      "Consumer Cyclical",
    "consumer_defensive":     "Consumer Defensive",
    "communication_services": "Communication Services",
    "industrials":            "Industrials",
    "energy":                 "Energy",
    "utilities":              "Utilities",
    "basic_materials":        "Basic Materials",
    "realestate":             "Real Estate",
}

# Free-form spellings → canonical key (lower-cased, stripped before lookup).
_SECTOR_ALIASES: dict[str, str] = {
    "real estate": "realestate",
    "real_estate": "realestate",
    "financial services": "financial_services",
    "financial": "financial_services",
    "financials": "financial_services",
    "consumer cyclical": "consumer_cyclical",
    "consumer discretionary": "consumer_cyclical",
    "consumer defensive": "consumer_defensive",
    "consumer staples": "consumer_defensive",
    "communication services": "communication_services",
    "communication": "communication_services",
    "telecommunications": "communication_services",
    "telecom services": "communication_services",
    "telecom": "communication_services",
    "basic materials": "basic_materials",
    "materials": "basic_materials",
    "health care": "healthcare",
    "info tech": "technology",
    "information technology": "technology",
}


def normalize_sector(name) -> str | None:
    """Map a free-form sector string to a canonical SECTOR_KEYS entry.
    Returns None if the name is empty or unrecognised.
    """
    if not name:
        return None
    key = str(name).strip().lower()
    if key in SECTOR_KEYS:
        return key
    return _SECTOR_ALIASES.get(key)


# Each scenario: sector_key → fractional shock (e.g. -0.30 = -30%).
SECTOR_STRESS_SCENARIOS: dict[str, dict[str, float]] = {
    "2008 Financial Crisis": {
        "financial_services":     -0.55,
        "realestate":             -0.40,
        "consumer_cyclical":      -0.35,
        "industrials":            -0.32,
        "energy":                 -0.30,
        "basic_materials":        -0.28,
        "technology":             -0.32,
        "communication_services": -0.28,
        "consumer_defensive":     -0.18,
        "healthcare":             -0.20,
        "utilities":              -0.22,
    },
    "Dot-Com Crash (Tech)": {
        "technology":             -0.50,
        "communication_services": -0.40,
        "consumer_cyclical":      -0.15,
        "industrials":            -0.10,
        "financial_services":     -0.12,
        "energy":                  0.05,
        "consumer_defensive":     -0.03,
        "healthcare":             -0.05,
        "utilities":               0.00,
        "basic_materials":        -0.10,
        "realestate":             -0.05,
    },
    "Rate Hike (2022-style)": {
        "technology":             -0.30,
        "consumer_cyclical":      -0.25,
        "communication_services": -0.30,
        "realestate":             -0.25,
        "utilities":              -0.10,
        "financial_services":      0.05,
        "healthcare":             -0.10,
        "consumer_defensive":     -0.05,
        "industrials":            -0.10,
        "basic_materials":        -0.12,
        "energy":                  0.15,
    },
    "Energy Shock (Oil +50%)": {
        "energy":                  0.45,
        "industrials":            -0.12,
        "consumer_cyclical":      -0.15,
        "consumer_defensive":     -0.05,
        "utilities":              -0.08,
        "technology":             -0.08,
        "financial_services":     -0.05,
        "communication_services": -0.05,
        "healthcare":              0.00,
        "basic_materials":         0.10,
        "realestate":             -0.05,
    },
    "Mild Correction (-10%)": {k: -0.10 for k in SECTOR_KEYS},
    "Severe Drawdown (-30%)": {k: -0.30 for k in SECTOR_KEYS},
    "Bull Run (+15%)":        {k:  0.15 for k in SECTOR_KEYS},
}

# Default per-asset-type shocks paired with each named scenario (for Bond,
# Cash, Crypto — i.e. things not covered by sector_weightings).
NON_EQUITY_SHOCKS: dict[str, dict[str, float]] = {
    "2008 Financial Crisis":   {"Bond":  0.08, "Crypto": -0.50, "Cash":  0.00, "CD":  0.00},
    "Dot-Com Crash (Tech)":    {"Bond":  0.05, "Crypto":  0.00, "Cash":  0.00, "CD":  0.00},
    "Rate Hike (2022-style)":  {"Bond": -0.18, "Crypto": -0.40, "Cash":  0.00, "CD":  0.00},
    "Energy Shock (Oil +50%)": {"Bond": -0.05, "Crypto": -0.10, "Cash":  0.00, "CD":  0.00},
    "Mild Correction (-10%)":  {"Bond": -0.02, "Crypto": -0.20, "Cash":  0.00, "CD":  0.00},
    "Severe Drawdown (-30%)":  {"Bond":  0.03, "Crypto": -0.50, "Cash":  0.00, "CD":  0.00},
    "Bull Run (+15%)":         {"Bond": -0.05, "Crypto":  0.30, "Cash":  0.00, "CD":  0.00},
}

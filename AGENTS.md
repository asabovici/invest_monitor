# Agents

invest-monitor ships two conversational agents, both powered by **Claude Opus 4.6 with adaptive thinking** and the Anthropic beta tool runner. Each agent maintains multi-turn conversation history so follow-up questions work without repeating context.

---

## Shared architecture

```
User prompt
    │
    ▼
Agent (RiskAgent / WealthAgent)
    │  maintains messages[]
    ▼
Anthropic tool runner  ←─── skills (beta_tool functions)
    │  loops until no more tool calls               │
    │                                               │
    ▼                                               ▼
Final text response                        Database / ReportingEngine
```

Skills are created by factory functions (`create_risk_skills`, `create_wealth_skills`) that close over a shared `Database` and `ReportingEngine` instance. The tool runner automatically invokes whichever skills Claude decides it needs, then returns the final answer.

Price data is a prerequisite for most analytical skills. If it is missing, run:

```bash
uv run invest-monitor collect --portfolio "<name>"
```

---

## Risk Agent

**Class:** `src/agent/agent.py:RiskAgent`
**CLI:** `invest-monitor agent`
**Skills file:** `src/agent/skills.py`

Focused on measuring and stress-testing portfolio risk. Flags concentration, correlation, tail risk, and historical/simulated downside scenarios.

### CLI usage

```bash
# Interactive session — opens with a full risk assessment
uv run invest-monitor agent --portfolio "My Portfolio"

# Interactive session — no opening prompt
uv run invest-monitor agent

# One-shot query
uv run invest-monitor agent --query "Which of my portfolios has the highest VaR?"
uv run invest-monitor agent --portfolio "My Portfolio" --query "How correlated are my positions?"
```

### Skills (13 total)

#### Portfolio overview

| Skill | Description |
|---|---|
| `list_portfolios` | List all portfolios in the database. |
| `get_portfolio_summary` | All positions with ticker, asset type, sector, quantity, cost basis, market value, and percentage weight. Sorted by market value. |

#### Risk analytics

| Skill | Description |
|---|---|
| `get_risk_metrics` | Annualised volatility, historical VaR (95%), Monte Carlo VaR (95%), and annualised covariance matrix. |
| `get_exposure_breakdown` | Exposure grouped by asset type and sector — dollar value and percentage weight per group. |
| `check_concentration_risk(threshold_pct=20)` | Identifies any position whose portfolio weight exceeds the threshold. Returns ticker, current weight, and excess over threshold. |
| `get_correlation_matrix` | Pairwise return correlations. Automatically flags pairs with \|correlation\| ≥ 0.7 and characterises them as hedges or undiversified bets. |

#### Performance & drawdown

| Skill | Description |
|---|---|
| `calculate_max_drawdown` | Peak-to-trough decline for each asset and for the dollar-weighted portfolio. Reports both the maximum historical drawdown and the current drawdown from peak. |
| `get_price_performance` | Price return over 1M, 3M, 6M, and 1Y look-back periods for each asset. |
| `get_cumulative_returns(start_date?)` | Total cumulative return from the earliest available price (or a given ISO date) to the most recent price, per asset. |

#### Scenario analysis

| Skill | Description |
|---|---|
| `list_stress_scenarios` | Lists all named built-in scenarios with their descriptions. |
| `run_stress_test(scenario_name)` | Applies a named historical or macro scenario to the portfolio. Sector-level shocks override asset-type shocks when a position's sector matches. Returns P&L per position and portfolio total. |
| `apply_custom_shock(shocks_json)` | Apply arbitrary % shocks to any combination of tickers, asset types, or sectors. `shocks_json` is a JSON object e.g. `{"AAPL": -15, "Technology": -10, "Bond": 5}`. Priority order: ticker > sector > asset type. |
| `simulate_forward(days=63, num_simulations=5000)` | Monte Carlo forward simulation using the full historical covariance matrix (Cholesky decomposition). Returns P5/P25/P50/P75/P95 portfolio value outcomes and probability of loss. |

#### Built-in stress scenarios

| ID | Description |
|---|---|
| `2008_financial_crisis` | S&P 500 −56 %, investment-grade bonds +8 %. Oct 2007–Mar 2009. |
| `covid_crash_2020` | S&P 500 −34 % in five weeks. Feb–Mar 2020. |
| `dot_com_bust` | Nasdaq −78 %, S&P 500 −49 %. Mar 2000–Oct 2002. |
| `rate_hike_shock` | Bonds −20 %, growth stocks −30 %, energy +50 %. 2022-style. |
| `inflation_spike` | Commodities +25 %, long bonds −25 %, growth equities −20 %. |

---

## Wealth Agent

**Class:** `src/agent/wealth_agent.py:WealthAgent`
**CLI:** `invest-monitor wealth`
**Skills file:** `src/agent/wealth_skills.py`

Focused on growing and preserving wealth: current P&L, goal planning, rebalancing, portfolio optimisation, and tax efficiency. Deliberately avoids duplicating the risk agent's metrics.

### CLI usage

```bash
# Interactive session — opens with a full wealth overview
uv run invest-monitor wealth --portfolio "My Portfolio"

# Interactive session — no opening prompt
uv run invest-monitor wealth

# One-shot queries
uv run invest-monitor wealth --query "Am I on track to reach $500k in 10 years with $1000/month?"
uv run invest-monitor wealth --portfolio "My Portfolio" --query "Optimise my allocation"
uv run invest-monitor wealth --portfolio "My Portfolio" --query "Should I rebalance to 60/40?"
```

### Skills (9 total)

#### Portfolio value & returns

| Skill | Description |
|---|---|
| `list_portfolios` | List all portfolios in the database. |
| `get_portfolio_value` | Current market value of each position using the latest stored price, alongside cost basis and unrealised P&L (absolute and %). |
| `get_total_return` | Return per position, split into winners (>+0.5%), losers (<−0.5%), and flat. Includes portfolio-level total return. |

#### Risk-adjusted performance

| Skill | Description |
|---|---|
| `calculate_sharpe_ratio(risk_free_rate_pct=4.5)` | Annualised Sharpe ratio and Sortino ratio. The Sortino uses downside deviation only, making it more informative for non-symmetric return distributions. |
| `get_diversification_score` | 0–100 composite score weighted across three factors: concentration (40 %, via Herfindahl-Hirschman Index), breadth (30 %, unique sectors + asset types), and average pairwise correlation (30 %). Rated Excellent / Good / Moderate / Poor. |

#### Rebalancing & optimisation

| Skill | Description |
|---|---|
| `suggest_rebalance(target_allocation_json)` | Compares current weights to a target allocation and outputs BUY / SELL / HOLD trades with dollar amounts and share counts. Accepts targets by asset type (`{"Stock": 60, "Bond": 40}`) or by ticker (`{"AAPL": 50, "BND": 50}`). Weights must sum to 100. |
| `optimize_allocation` | Mean-variance optimisation returning three portfolios: **equal weight**, **minimum variance** (lowest achievable volatility), and **maximum Sharpe** (best risk-adjusted return at 4.5% risk-free rate). Uses `scipy.optimize.minimize` with SLSQP. |

#### Goal planning

| Skill | Description |
|---|---|
| `run_goal_projection(goal_amount, years, monthly_contribution=0, num_simulations=5000)` | Monte Carlo projection of whether the portfolio reaches a target value by a deadline, with optional ongoing contributions. Returns probability of success, expected value, and P10/P25/P50/P75/P90 outcomes. |

#### Tax efficiency

| Skill | Description |
|---|---|
| `find_tax_loss_opportunities(min_loss_pct=5)` | Identifies positions with unrealised losses exceeding the threshold — candidates for tax-loss harvesting. Also flags positions with large unrealised gains (>20%) for tax-planning awareness. Always returns a disclaimer that this is not tax advice. |

---

## Research Agent

**Class:** `src/agent/research_agent.py:ResearchAgent`
**CLI:** `invest-monitor research`
**Skills file:** `src/agent/research_skills.py`

Finds the best way to deploy a given amount of capital while respecting explicit portfolio constraints (sector exposure limits, VaR budgets, drawdown ceilings). Combines **live web search** (Anthropic-hosted `web_search_20260209` server-side tool) with portfolio simulation skills to research candidates and stress-test proposed allocations before committing.

### CLI usage

```bash
# Interactive session — opens with a portfolio baseline
uv run invest-monitor research --portfolio "My Portfolio"

# One-shot research queries
uv run invest-monitor research --query "How can I deploy $100k without increasing software sector exposure or VaR?"
uv run invest-monitor research --portfolio "My Portfolio" --query "Find bond ETFs that reduce my overall drawdown"
uv run invest-monitor research --portfolio "My Portfolio" --query "I want to add $50k in commodities exposure — what are the best options?"
```

### Typical agent workflow

```
1. get_portfolio_baseline   → establish current VaR, drawdown, sector weights
2. web_search               → find candidates that fit the stated constraints
3. lookup_asset_info        → verify sector, type, beta, correlation profile
4. fetch_asset_prices       → pull 1-year price history for candidates into the DB
5. simulate_allocation      → measure combined-portfolio deltas vs baseline
6. iterate                  → refine weights until all constraints are satisfied
7. present ranked shortlist → position sizes, reasoning, sources cited
```

### Skills (5 portfolio tools + web search)

#### Discovery & data

| Skill | Description |
|---|---|
| `list_portfolios` | List all portfolios in the database. |
| `lookup_asset_info(tickers_csv)` | Live yfinance lookup for one or more tickers (comma-separated): name, sector, industry, asset type, current price, 52-week range, beta, market cap. |
| `fetch_asset_prices(tickers_csv, period="1y")` | Download price history from Yahoo Finance and save to the local database. Also saves asset metadata (name, sector, type) so tickers can be used in simulations. Always call this before `simulate_allocation` for new tickers. |

#### Baseline & simulation

| Skill | Description |
|---|---|
| `get_portfolio_baseline(portfolio_name)` | Current risk snapshot: total value, sector breakdown (%), annualised volatility, historical VaR (95%), and max drawdown. Use as the "before" reference. |
| `simulate_allocation(portfolio_name, allocation_json, total_amount)` | Core constraint-checking skill. Extends the portfolio by `total_amount` dollars using the proposed allocation (`{"BND": 0.5, "VTI": 0.3, "GLD": 0.2}`) and reports: combined risk metrics, deltas vs baseline (volatility, VaR, drawdown), sector exposure before/after/delta, and correlation of each new asset with the existing portfolio. |

#### Web search (server-side)

| Tool | Description |
|---|---|
| `web_search` | Anthropic-hosted web search (`web_search_20260209`) with dynamic filtering. Claude uses this to find investment candidates, read analyst commentary, and verify sector classifications. Resolved entirely server-side — no client-side execution required. |

---

## Programmatic usage

Both agents can be used directly in Python, not just from the CLI.

```python
from src.agent import RiskAgent, WealthAgent, ResearchAgent

# Risk agent — interactive
agent = RiskAgent()
agent.run_interactive(initial_portfolio="My Portfolio")

# Risk agent — single query (history retained across calls)
agent = RiskAgent()
print(agent.chat("What is the VaR of my Tech portfolio?"))
print(agent.chat("How does that compare under a 2008 scenario?"))  # follows up in context

# Wealth agent — one-shot
agent = WealthAgent()
print(agent.run_query("Am I on track to reach $1M in 15 years with $2000/month?"))

# Research agent — interactive with baseline opener
agent = ResearchAgent()
agent.run_interactive(initial_portfolio="My Portfolio")

# Research agent — constrained deployment query
agent = ResearchAgent()
print(agent.run_query(
    "How can I deploy $100k into my 'My Portfolio' without increasing "
    "software sector exposure or my overall VaR?"
))
```

`run_query` is equivalent to `chat` but is named to signal that no prior history is assumed.

# Agents

invest-monitor has **two distinct agent systems**:

1. **Conversational agents** (this document) — five single-actor tool-runners powered by Claude Opus 4.6, each maintaining its own chat history:
   - Analytics agents: **Risk**, **Wealth**, **Research**
   - Decision agents: **Portfolio Manager**, **CIO** — conversational counterparts to nodes in the LangGraph coordination system
2. **Multi-agent coordination graph** (`src/trading_graph/`) — a LangGraph pipeline with four nodes (Researcher → Portfolio Manager → Risk Manager → CIO) sharing a single `TradingState`, with a bounded PM ↔ Risk revision loop and an optional human-in-the-loop pause before the CIO signs off. Use this to produce a vetted trade proposal end-to-end. See [`docs/multi-agent-graph.md`](docs/multi-agent-graph.md).

The rest of this document covers the conversational agents.

---

## Conversational agents

The five conversational agents are all powered by **Claude Opus 4.6 with adaptive thinking** and the Anthropic beta tool runner. Each agent maintains multi-turn conversation history so follow-up questions work without repeating context.

You can talk to them three ways:
1. **CLI** — `invest-monitor agent`, `invest-monitor wealth`, `invest-monitor research`, `invest-monitor pm`, `invest-monitor cio`.
2. **Streamlit dashboard** — embedded chat panel at the bottom of the Multi-Portfolio Dashboard under **🤖 Ask the Agents**, with a tab per agent (Risk / Wealth / Research / PM / CIO). Each tab keeps its own history and is scoped to the active data dir (live vs demo).
3. **Programmatic** — `from src.agent import RiskAgent, WealthAgent, ResearchAgent, PortfolioManagerAgent, CIOAgent` (see end of file).

All three read `ANTHROPIC_API_KEY` from the environment. The simplest way is a project-local `.env` file (auto-loaded via `src/env.py`):

```bash
cp .env.example .env
# paste your key after ANTHROPIC_API_KEY=
```

Restart Streamlit / the CLI after editing `.env` — `load_dotenv()` runs at module import time.

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

Focused on growing and preserving wealth: current P&L, goal planning, rebalancing, portfolio optimisation, tax efficiency, and **scenario analysis** (named-scenario phases + cross-asset beta-implied shocks for an MC projection). Deliberately avoids duplicating the risk agent's metrics.

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

### Skills (11 total)

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

#### Scenario analysis

| Skill | Description |
|---|---|
| `list_scenarios` | Lists all named MC scenarios from `src/scenarios.py:SCENARIOS` (`base`, `market_crash`, `mild_correction`, `prolonged_low_growth`, `stagflation`, `bull_run`, `flash_crash_recovery`, `double_dip`, `rate_shock`) along with their phase structure, plus the `CROSS_ASSET_BETAS` table. |
| `run_scenario_analysis(portfolio_name, scenario_name="base", goal_amount?, years?, monthly_contribution?, shocked_asset_class?, shock_return_pct?)` | Scenario-aware Monte Carlo. Combines (a) named-scenario phases that modify daily μ/σ per trading day and apply one-time shocks, and (b) cross-asset beta-implied shocks (specify one asset class + its shock, every other class gets `beta × shock`). Returns P5–P95 percentiles, goal probability, and per-class shock breakdown. |

#### Tax efficiency

| Skill | Description |
|---|---|
| `find_tax_loss_opportunities(min_loss_pct=5)` | Identifies positions with unrealised losses exceeding the threshold — candidates for tax-loss harvesting. Also flags positions with large unrealised gains (>20%) for tax-planning awareness. Always returns a disclaimer that this is not tax advice. |

#### Reports

| Skill | Description |
|---|---|
| `export_report(filename, markdown_content, overwrite=False)` | Persist a wealth-review report as markdown under `<data_dir>/reports/`. The agent composes the content; the skill only handles I/O. |

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

## Portfolio Manager Agent

**Class:** `src/agent/portfolio_manager_agent.py:PortfolioManagerAgent`
**CLI:** `invest-monitor pm`
**Skills file:** `src/agent/pm_skills.py`

Conversational counterpart to the `portfolio_manager` node in `src/trading_graph/`. Translates a market view (or a CIO follow-up) into a concrete, defensible trade proposal that the Risk Manager and CIO can review. The agent builds proposals; it does not sign off.

### CLI usage

```bash
# Interactive session — opens with a portfolio snapshot prompt
uv run invest-monitor pm --portfolio "My Portfolio"

# One-shot queries
uv run invest-monitor pm --query "Propose a 60/40 deployment of \$50k into VTI and BND"
uv run invest-monitor pm --portfolio "My Portfolio" --query "Rebalance to equal-weight across all current holdings"
```

### Skills (6 total)

| Skill | Description |
|---|---|
| `list_portfolios` | List all portfolios available. |
| `get_portfolio_snapshot(portfolio_name)` | Current positions with quantity, cost basis per share, latest price, market value, and weight %. PM-focused — no risk metrics. |
| `propose_trades(portfolio_name, target_allocation_json, total_amount, rebalance_mode="deploy")` | Convert a target allocation into concrete BUY/SELL orders. `rebalance_mode="deploy"` adds new capital on top of existing holdings; `"rebalance"` treats `total_amount` as the desired total portfolio value. Allocation weights can be fractions or percents — they're normalised. |
| `compare_to_target(portfolio_name, target_allocation_json)` | Current vs target weight per ticker, with delta and a verdict (increase / decrease / hold). |
| `estimate_sector_tilt(portfolio_name, target_allocation_json, total_amount)` | Sector exposure before and after applying the proposed allocation. |
| `summarise_proposal(portfolio_name, target_allocation_json, total_amount, rationale)` | Emit a clean structured proposal record (text + JSON) for hand-off to the CIO. |
| `export_report(filename, markdown_content, overwrite=False)` | Persist a proposal brief as markdown under `<data_dir>/reports/`. |

---

## CIO Agent

**Class:** `src/agent/cio_agent.py:CIOAgent`
**CLI:** `invest-monitor cio`
**Skills file:** `src/agent/cio_skills.py`

Conversational counterpart to the `cio` node in `src/trading_graph/`. Holistic oversight: reviews proposals against firm-level concentration and sector caps and produces one of three structured decisions — approve, override, or request more research. Does not execute trades; `approve_proposal` emits a sign-off record only.

### CLI usage

```bash
# Interactive session — opens with a holistic CIO view
uv run invest-monitor cio --portfolio "My Portfolio"

# One-shot queries
uv run invest-monitor cio --query "Review this proposal: deploy \$25k as {AAPL: 0.5, MSFT: 0.5} into My Portfolio"
uv run invest-monitor cio --portfolio "My Portfolio" --query "What's our biggest concentration risk right now?"
```

### Skills (6 total)

| Skill | Description |
|---|---|
| `list_portfolios` | List all portfolios available. |
| `get_holistic_view(portfolio_name, top_n=5)` | CIO single-screen: total value, top N positions, sector concentration, one-line risk headline. |
| `review_proposal(portfolio_name, target_allocation_json, total_amount, max_position_pct=30, max_sector_pct=40)` | Score the proposal against high-level CIO thresholds. Flags any per-position weight above `max_position_pct` (post-deploy) and any sector exposure above `max_sector_pct`. Returns a `PASSES CIO CHECKS` or `REQUEST CHANGES` verdict. |
| `approve_proposal(portfolio_name, target_allocation_json, total_amount, signoff_note)` | Formal sign-off record (text + JSON). |
| `override_proposal(portfolio_name, original_allocation_json, override_allocation_json, total_amount, reason)` | Replace the PM's proposal with the CIO's version + concrete reason. |
| `request_more_research(question, scope="general")` | Brief the Researcher with a specific question rather than a blanket rejection. |
| `export_report(filename, markdown_content, overwrite=False)` | Persist a CIO decision memo as markdown under `<data_dir>/reports/`. |

---

## Exporting reports

The Wealth, PM, and CIO agents share an `export_report(filename, markdown_content, overwrite=False)` skill. The agent composes the full markdown body in conversation (so the report inherits whatever context you've built up with it) and hands it to the skill for persistence. The skill:

- Writes to `<data_dir>/reports/<filename>` (auto-created), scoped to the active dataset (live vs demo).
- Sanitises the filename — path components are stripped, non-`[A-Za-z0-9._-]` characters are replaced with `_`, and a `.md` extension is appended if missing.
- Refuses to overwrite an existing file unless the agent passes `overwrite=True`.
- Prepends a `<!-- generated by <agent> at <iso8601> -->` comment for traceability (invisible in rendered markdown).

The `reports/` directory is gitignored via `data*/reports/`.

Trigger any of them with prompts like:

- *"Write up a wealth review for 'My Portfolio' and save it as `wealth_review_2026q2.md`."*
- *"Persist this proposal as `tech_rotation_proposal.md`."*
- *"Save the CIO memo for that decision as `cio_memo_my_portfolio_2026q2.md`."*

---

## Programmatic usage

All five agents can be used directly in Python, not just from the CLI.

```python
from src.agent import (
    RiskAgent, WealthAgent, ResearchAgent,
    PortfolioManagerAgent, CIOAgent,
)

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

# Portfolio Manager — build a proposal
pm = PortfolioManagerAgent()
print(pm.chat(
    "Snapshot 'My Portfolio' and propose how to deploy $25k across "
    "BND and VTI 50/50. Summarise the final proposal."
))

# CIO — review and decide
cio = CIOAgent()
print(cio.chat(
    'Review this proposal for "My Portfolio": deploy $25k as '
    '{"BND": 0.5, "VTI": 0.5}. Approve, override, or kick back?'
))
```

`run_query` is equivalent to `chat` but is named to signal that no prior history is assumed.

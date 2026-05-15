# AI Agents

Three conversational agents powered by **Claude Opus 4.6 with adaptive thinking** and the Anthropic beta tool runner. Each maintains multi-turn conversation history.

## Access channels

=== "CLI"

    ```bash
    invest-monitor agent --portfolio "My Portfolio"      # Risk
    invest-monitor wealth --portfolio "My Portfolio"      # Wealth
    invest-monitor research --portfolio "My Portfolio"   # Research

    # One-shot queries
    invest-monitor agent --query "Which portfolio has the highest VaR?"
    invest-monitor wealth --query "Am I on track to reach $500k in 10y?"
    ```

=== "Dashboard"

    Multi-Portfolio Dashboard → **🤖 Ask the Agents** section. Three tabs (Risk / Wealth / Research). Each tab keeps its own history and is scoped to the active data dir (live vs demo). Lazy instantiation: the `Anthropic()` client is only built when you send the first message in a tab, so a missing `ANTHROPIC_API_KEY` shows a clear inline error instead of crashing the dashboard.

=== "Programmatic"

    ```python
    from src.agent import RiskAgent, WealthAgent, ResearchAgent

    agent = RiskAgent()
    print(agent.chat("What's the VaR of my Tech portfolio?"))
    print(agent.chat("How does that compare under a 2008 scenario?"))

    agent = ResearchAgent()
    agent.run_interactive(initial_portfolio="My Portfolio")
    ```

## Configuration

Each agent reads `ANTHROPIC_API_KEY` from the environment. Set it via [`.env`](getting-started.md#anthropic-api-key) (auto-loaded) or shell export.

## Risk Agent (13 skills)

| Category | Skills |
|---|---|
| Portfolio overview | `list_portfolios`, `get_portfolio_summary` |
| Risk analytics | `get_risk_metrics`, `get_exposure_breakdown`, `check_concentration_risk`, `get_correlation_matrix` |
| Performance & drawdown | `calculate_max_drawdown`, `get_price_performance`, `get_cumulative_returns` |
| Scenario analysis | `list_stress_scenarios`, `run_stress_test`, `apply_custom_shock`, `simulate_forward` |

Built-in stress scenarios: `2008_financial_crisis`, `covid_crash_2020`, `dot_com_bust`, `rate_hike_shock`, `inflation_spike`.

## Wealth Agent (11 skills)

| Category | Skills |
|---|---|
| Portfolio value & returns | `list_portfolios`, `get_portfolio_value`, `get_total_return` |
| Risk-adjusted | `calculate_sharpe_ratio`, `get_diversification_score` |
| Rebalancing & optimisation | `suggest_rebalance`, `optimize_allocation` |
| Goal planning | `run_goal_projection` |
| Tax efficiency | `find_tax_loss_opportunities` |
| Scenario analysis | `list_scenarios`, `run_scenario_analysis` |

`run_scenario_analysis` is the killer one — scenario-aware Monte Carlo that combines named-scenario phases (modifying daily μ/σ per trading day) with beta-implied cross-asset shocks.

## Research Agent (5 skills + web search)

| Skill | Description |
|---|---|
| `list_portfolios` | List portfolios in the DB. |
| `lookup_asset_info(tickers_csv)` | Live yfinance lookup: name, sector, industry, asset type, current price, 52-week range, beta, market cap. |
| `fetch_asset_prices(tickers_csv, period="1y")` | Download price history into the local DB. Always call before `simulate_allocation` for new tickers. |
| `get_portfolio_baseline(portfolio_name)` | "Before" reference: current vol, VaR, max drawdown, sector breakdown. |
| `simulate_allocation(portfolio_name, allocation_json, total_amount)` | Extends the portfolio by `total_amount` using the proposed allocation. Reports combined risk metrics, deltas vs baseline, sector exposure before/after, and correlation of each new asset with the existing portfolio. |
| `web_search` | Anthropic-hosted server-side web search (`web_search_20260209`). Used to find investment candidates, read analyst commentary, verify sector classifications. |

### Typical workflow

```
1. get_portfolio_baseline    → "before" risk snapshot
2. web_search                → find candidates fitting stated constraints
3. lookup_asset_info         → verify sector, type, beta
4. fetch_asset_prices        → pull 1y prices for candidates
5. simulate_allocation       → measure combined-portfolio deltas vs baseline
6. iterate                   → refine weights until constraints satisfied
7. present ranked shortlist  → position sizes, reasoning, sources cited
```

### Example queries

- *"How can I deploy $100k without increasing software sector exposure or VaR?"*
- *"Find bond ETFs that reduce my overall drawdown."*
- *"I want $50k in commodities exposure — what are the best options?"*

# AI Agents

Five conversational agents powered by **Claude Opus 4.6 with adaptive thinking** and the Anthropic beta tool runner. Each maintains multi-turn conversation history.

The five agents fall into two groups:

- **Analytics agents** (Risk, Wealth, Research) — single-actor tool-runners focused on diagnosing, planning, and discovering.
- **Decision agents** (Portfolio Manager, CIO) — conversational counterparts to nodes in the [Multi-Agent Graph](multi-agent-graph.md). PM builds proposals; CIO reviews them and produces a structured approve / override / more-research decision.

## Access channels

=== "CLI"

    ```bash
    invest-monitor agent --portfolio "My Portfolio"      # Risk
    invest-monitor wealth --portfolio "My Portfolio"     # Wealth
    invest-monitor research --portfolio "My Portfolio"   # Research
    invest-monitor pm --portfolio "My Portfolio"         # Portfolio Manager
    invest-monitor cio --portfolio "My Portfolio"        # CIO

    # One-shot queries
    invest-monitor agent --query "Which portfolio has the highest VaR?"
    invest-monitor wealth --query "Am I on track to reach $500k in 10y?"
    invest-monitor pm --query "Propose a 60/40 deployment of $50k into VTI and BND"
    invest-monitor cio --query "Review this proposal: deploy $25k as {AAPL: 0.5, MSFT: 0.5}"
    ```

=== "Dashboard"

    Multi-Portfolio Dashboard → **🤖 Ask the Agents** section. Five tabs (Risk / Wealth / Research / PM / CIO). Each tab keeps its own history and is scoped to the active data dir (live vs demo). Lazy instantiation: the `Anthropic()` client is only built when you send the first message in a tab, so a missing `ANTHROPIC_API_KEY` shows a clear inline error instead of crashing the dashboard.

    Each tab also has a **💾 Save summary** button (compress + persist the chat) and a **📂 Load past conversation context** expander (re-prime the agent with any past summary, even from a different agent). See [Conversation Summaries](conversation-summaries.md).

=== "Programmatic"

    ```python
    from src.agent import (
        RiskAgent, WealthAgent, ResearchAgent,
        PortfolioManagerAgent, CIOAgent,
    )

    agent = RiskAgent()
    print(agent.chat("What's the VaR of my Tech portfolio?"))
    print(agent.chat("How does that compare under a 2008 scenario?"))

    pm = PortfolioManagerAgent()
    print(pm.chat("Snapshot 'My Portfolio' and propose a deployment of $25k into BND + VTI 50/50."))

    cio = CIOAgent()
    print(cio.chat('Review this proposal: {"BND": 0.5, "VTI": 0.5} for $25k into "My Portfolio".'))
    ```

## Configuration

Each agent reads `ANTHROPIC_API_KEY` from the environment. Set it via [`.env`](getting-started.md#anthropic-api-key) (auto-loaded) or shell export.

## Exporting reports to markdown

The **Wealth**, **PM**, and **CIO** agents share an `export_report(filename, markdown_content, overwrite=False)` skill. The agent composes the report body itself (so it inherits everything you've been discussing in the chat) and hands it to the skill for persistence. Files land in `<data_dir>/reports/`, scoped to the active dataset (live vs demo). Filenames are sanitised, an `.md` extension is appended if missing, and the agent must pass `overwrite=True` to replace an existing file. Triggering examples:

- *"Write up a wealth-review report for 'My Portfolio' and save it as `my_portfolio_wealth_review_2026q2.md`."*
- *"Persist this proposal as `tech_rotation_proposal.md`."*
- *"Save the CIO memo for that decision — file it as `cio_memo_my_portfolio_2026q2.md`."*

The `reports/` directory is gitignored (`data*/reports/`).

## Risk Agent (13 skills)

| Category | Skills |
|---|---|
| Portfolio overview | `list_portfolios`, `get_portfolio_summary` |
| Risk analytics | `get_risk_metrics`, `get_exposure_breakdown`, `check_concentration_risk`, `get_correlation_matrix` |
| Performance & drawdown | `calculate_max_drawdown`, `get_price_performance`, `get_cumulative_returns` |
| Scenario analysis | `list_stress_scenarios`, `run_stress_test`, `apply_custom_shock`, `simulate_forward` |

Built-in stress scenarios: `2008_financial_crisis`, `covid_crash_2020`, `dot_com_bust`, `rate_hike_shock`, `inflation_spike`.

## Wealth Agent (12 skills)

| Category | Skills |
|---|---|
| Portfolio value & returns | `list_portfolios`, `get_portfolio_value`, `get_total_return` |
| Risk-adjusted | `calculate_sharpe_ratio`, `get_diversification_score` |
| Rebalancing & optimisation | `suggest_rebalance`, `optimize_allocation` |
| Goal planning | `run_goal_projection` |
| Tax efficiency | `find_tax_loss_opportunities` |
| Scenario analysis | `list_scenarios`, `run_scenario_analysis` |
| Reports | `export_report` (markdown → `<data_dir>/reports/`) |

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

## Portfolio Manager Agent (7 skills)

Conversational counterpart to the `portfolio_manager` node in [`src/trading_graph/`](multi-agent-graph.md). Its job is to translate a market view (or a CIO follow-up) into a concrete, defensible trade proposal.

| Skill | Description |
|---|---|
| `list_portfolios` | List portfolios in the DB. |
| `get_portfolio_snapshot(portfolio_name)` | Current positions, weights, market value — the "what do we own right now?" view. |
| `propose_trades(portfolio_name, target_allocation_json, total_amount, rebalance_mode="deploy")` | Convert a target allocation into BUY/SELL orders with dollar amounts and share counts. `rebalance_mode="deploy"` adds new capital; `"rebalance"` treats `total_amount` as the desired total portfolio value. |
| `compare_to_target(portfolio_name, target_allocation_json)` | Current weight vs target weight per ticker, with delta and verdict (increase / decrease / hold). |
| `estimate_sector_tilt(portfolio_name, target_allocation_json, total_amount)` | Sector exposure before and after applying the proposal. |
| `summarise_proposal(portfolio_name, target_allocation_json, total_amount, rationale)` | Emit a clean structured proposal record (text + JSON) for hand-off to the CIO. |
| `export_report(filename, markdown_content, overwrite=False)` | Persist a proposal brief as markdown under `<data_dir>/reports/`. The agent composes the body; the skill only handles I/O. |

### Example queries

- *"Snapshot 'My Portfolio' and propose how to deploy $25k across BND and VTI, 50/50."*
- *"Rebalance 'My Portfolio' to equal weight across all current holdings."*
- *"Risk flagged software concentration — revise the previous proposal to cut tech weight in half."*

## CIO Agent (7 skills)

Conversational counterpart to the `cio` node. Reviews proposals against firm-level concentration and sector caps, and produces one of three structured decisions: approve, override, or request more research.

| Skill | Description |
|---|---|
| `list_portfolios` | List portfolios in the DB. |
| `get_holistic_view(portfolio_name, top_n=5)` | Top-down view: total value, top positions, sector concentration, risk headline. |
| `review_proposal(portfolio_name, target_allocation_json, total_amount, max_position_pct=30, max_sector_pct=40)` | Quantifies sector tilt and flags any per-position or sector cap breaches post-deploy. Returns a `PASSES CIO CHECKS` or `REQUEST CHANGES` verdict. |
| `approve_proposal(portfolio_name, target_allocation_json, total_amount, signoff_note)` | Emits a formal CIO sign-off record (text + JSON). Does not execute trades. |
| `override_proposal(portfolio_name, original_allocation_json, override_allocation_json, total_amount, reason)` | Replace the PM's proposal with the CIO's version and record the reason. |
| `request_more_research(question, scope="general")` | Kicks back to the Researcher with a specific question rather than a blanket rejection. |
| `export_report(filename, markdown_content, overwrite=False)` | Persist a CIO decision memo as markdown under `<data_dir>/reports/`. |

### Example queries

- *"Give me a CIO view of 'My Portfolio'."*
- *"Review this proposal: deploy $50k as {VTI: 0.6, BND: 0.4} into 'My Portfolio'."*
- *"The PM is proposing {AAPL: 0.5, MSFT: 0.5} for $30k — does it pass our concentration caps?"*

# Portfolio Groups

Many-to-many tagging for portfolios. Lets you scope the Multi-Portfolio Dashboard to a subset (e.g. *Taxable*, *Tax-Free*, *Retirement*) and optionally **merge that subset into one synthetic portfolio** for benchmark comparison and projection.

A portfolio can belong to multiple groups — SCHAB can be simultaneously in *Taxable* and *Brokerage*; PRU401K can be in *Tax-Free* and *Retirement*.

## Three ways to manage groups

=== "Sidebar — 🏷 Portfolio Groups"

    The expander has two halves:

    - **Create / update** — name + optional description.
    - **Manage memberships** — select a group, edit its members via a multiselect, save atomically. Also a Delete button (member portfolios are untouched).

=== "Single Portfolio → 📊 Overview"

    A `🏷 Groups` multiselect at the top of the Overview tab lets you tag/untag the currently-loaded portfolio without navigating to the sidebar. Saves changes via `set_groups_for_portfolio` — one atomic write per save.

    The sidebar's **Active:** line shows current group memberships as badges (`🏷 Taxable, Brokerage`).

=== "CLI"

    ```bash
    invest-monitor group list                              # all groups + members
    invest-monitor group create "Tax-Free" --description "Roth + HSA + 401k"
    invest-monitor group add "Tax-Free" "PRU401K"
    invest-monitor group remove "Tax-Free" "PRU401K"
    invest-monitor group show "SCHAB"                      # which groups it's in
    invest-monitor group delete "Tax-Free"                 # removes group + clears memberships
    ```

## Group filter on the dashboard

When at least one group exists, a **Group filter** selectbox appears at the top of the Multi-Portfolio Dashboard. Picking a group scopes **every** section below to its members:

- KPI strip (Portfolios / Positions / Total Cost / Current Value / Unrealised P&L)
- Aggregate Exposure (donut + sector bar + Top 15 underlying)
- Summary table (returns, vol, VaR, drawdowns)
- Comparison charts
- Income Projection
- Performance Attribution (cumulative-return, drawdown, contributors)
- Wealth Projection (Deterministic + Monte Carlo + SWR)
- Agent chat scope

## View as combined portfolio

When a group is active, a **"View as combined portfolio"** toggle appears next to the filter. Flipping it on merges the group's member portfolios into one synthetic entity named `"{group} (combined)"`:

| Field | Behaviour |
|---|---|
| Position quantity | **Summed** across members |
| Position cost basis | **Weighted average**: `Σ(qty_i × cb_i) / Σ qty_i` |
| Asset metadata (ticker, name, type, sector) | Taken from the first member encountered for that ticker |
| Daily `total_value` (for attribution) | Summed across members per date |
| `daily_return / cum_return / drawdown / rolling_vol_21d` | Re-derived from the merged `total_value` series — **not** averaged across members' metrics |

Why the per-date re-derivation? Averaging members' `daily_return` would mis-weight portfolios of different sizes. Re-deriving from the value sum gives the correct value-weighted return.

**Invariance**: `Σ(member total_cost) = combined total_cost`. Same for current value. Lookthrough and stress tests follow the same invariance properties as elsewhere — see [Lookthrough](lookthrough.md).

## Why this matters

Pair this feature with **[Benchmarks](benchmarks.md)** for the killer "how am I doing?" workflow:

1. Define a group (e.g. *Tax-Free* = Roth IRA + HSA + 401k).
2. Filter the dashboard to it.
3. Flip **"View as combined portfolio"**.
4. In Performance Attribution, overlay **All Seasons** + **60/40 Classic**.
5. The chart now shows one cumulative-return line for your aggregate tax-free pot vs the two benchmarks, with a vs-benchmark delta table.

If you're managing a household across several accounts, this is the level of analysis you actually need — *"is our retirement money beating 60/40 over the last year?"* — not the per-account silos.

## Storage

Two parquet stores, same pattern as `portfolios.parquet` / `positions.parquet`:

| File | Schema |
|---|---|
| `groups.parquet` | `name, description, created_at` |
| `portfolio_groups.parquet` | `group_name, portfolio_name` (many-to-many) |

Auto-migrated like everything else. Demo and live modes have independent group registries.

## Database API

```python
from src.database import Database
db = Database()

# Registry
db.list_groups()                                   # → ["Taxable", "Tax-Free", ...]
db.get_group_description("Tax-Free")               # → "Roth + HSA + 401k" or None
db.create_group("Tax-Free", "Roth + HSA + 401k")   # upsert
db.delete_group("Tax-Free")                        # cascades into memberships

# Membership (from the group side)
db.get_group_members("Tax-Free")                   # → ["PRU401K", "ROTH_IRA"]
db.add_to_group("Tax-Free", "PRU401K")             # idempotent
db.remove_from_group("Tax-Free", "PRU401K")
db.set_group_members("Tax-Free", ["A", "B", "C"])  # atomic replace

# Membership (from the portfolio side)
db.get_groups_for_portfolio("SCHAB")               # → ["Brokerage", "Taxable"]
db.set_groups_for_portfolio("SCHAB", ["Taxable"])  # atomic replace
```

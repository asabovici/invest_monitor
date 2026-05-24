# CLI Reference

Every command runs from the project root. With `uv`:

```bash
uv run invest-monitor <command>
```

…or activate the venv and call `invest-monitor` directly.

## Portfolios

```bash
invest-monitor load path/to/portfolio.csv --name "My Portfolio"
invest-monitor portfolio list
invest-monitor portfolio create "Crypto"       # empty portfolio
invest-monitor portfolio delete "My Portfolio"
```

## Prices

```bash
invest-monitor collect --period 1y
invest-monitor collect --period 1y --portfolio "My Portfolio"
```

Supported `--period` values: `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `max`.

## Reports

```bash
invest-monitor report "My Portfolio"
```

Prints the exposure breakdown and risk metrics for one portfolio to stdout.

## Daily metrics & attribution

Populates `daily_security_metrics.parquet`, `daily_portfolio_metrics.parquet`, `daily_attribution.parquet`:

```bash
invest-monitor metrics refresh                            # incremental (re-walks last 30d)
invest-monitor metrics refresh --portfolio "My Portfolio" # scope to one
invest-monitor metrics refresh --from 2024-01-01          # from a date
invest-monitor metrics refresh --full                     # recompute everything
```

v2 trade-replay is auto-selected per portfolio when `trades.parquet` has rows for it. See [Performance Attribution](performance-attribution.md).

## Conversation summaries

```bash
invest-monitor summaries list                              # newest first
invest-monitor summaries list --agent risk                 # filter
invest-monitor summaries show "risk__2026-05-17T14:30:00"  # full text
invest-monitor summaries delete "risk__2026-05-17T14:30:00"
```

See [Conversation Summaries](conversation-summaries.md).

## Portfolio groups

```bash
invest-monitor group list                              # all groups + members
invest-monitor group create "Tax-Free" --description "Roth + HSA + 401k"
invest-monitor group add "Tax-Free" "PRU401K"
invest-monitor group remove "Tax-Free" "PRU401K"
invest-monitor group show "SCHAB"                      # which groups it's in
invest-monitor group delete "Tax-Free"
```

See [Portfolio Groups](portfolio-groups.md).

## Benchmarks

```bash
invest-monitor benchmarks list                  # table + weights per benchmark
invest-monitor benchmarks fetch                 # default 10y proxy prices
invest-monitor benchmarks fetch --period 5y
```

See [Benchmarks](benchmarks.md).

## Production jobs

```bash
invest-monitor production status                          # job table + due flag
invest-monitor production run                             # run only what's due (cron-friendly)
invest-monitor production run-now refresh_attribution     # force-run one job
invest-monitor production daemon --check-every 60         # long-running loop

# systemd integration (Linux)
invest-monitor production schedule list
invest-monitor production schedule install refresh_attribution
invest-monitor production schedule install collect_prices --interval 720
invest-monitor production schedule uninstall refresh_attribution
```

See [Production](production.md).

## Demo dataset

```bash
invest-monitor demo seed                                  # idempotent
invest-monitor demo seed --reset                          # wipe & reseed
invest-monitor demo reset                                 # delete data_demo/
```

## AI agents

Each agent supports interactive + one-shot modes:

```bash
# Risk Agent
invest-monitor agent --portfolio "My Portfolio"
invest-monitor agent --query "Which portfolio has the highest VaR?"

# Wealth Agent
invest-monitor wealth --portfolio "My Portfolio"
invest-monitor wealth --query "Am I on track to reach $500k in 10y with $1000/mo?"

# Research Agent (includes web search)
invest-monitor research --portfolio "My Portfolio"
invest-monitor research --query "Deploy $100k without raising my software exposure"
```

See [AI Agents](ai-agents.md).

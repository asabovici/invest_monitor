import click
from tabulate import tabulate

from src import env as _env  # noqa: F401  — loads .env into os.environ
# Database is still imported because the `production daemon` command
# instantiates one for the long-running loop. Every other CLI command goes
# through src.services.*.
from src.database import Database
from src.agent import (
    CIOAgent,
    PortfolioManagerAgent,
    ResearchAgent,
    RiskAgent,
    WealthAgent,
)


@click.group()
def cli():
    pass


@cli.command()
@click.argument("csv_path")
@click.option("--name", default="", help="Portfolio name (defaults to CSV filename)")
@click.option("--data-dir", default="data", show_default=True)
def load(csv_path, name, data_dir):
    """Load a portfolio from a CSV file and save it to the database."""
    from pathlib import Path
    from src.services.portfolios import load_portfolio_from_csv
    resolved_name = name or Path(csv_path).stem
    csv_text = Path(csv_path).read_text(encoding="utf-8")
    detail = load_portfolio_from_csv(data_dir, resolved_name, csv_text)
    click.echo(f"Saved portfolio '{detail.name}' with {len(detail.positions)} positions.")


@cli.command()
@click.option("--period", default="1y", help="Collection period (e.g. 1y, 1mo)")
@click.option("--portfolio", "portfolio_name", default="", help="Collect only for a specific portfolio")
@click.option("--data-dir", default="data", show_default=True)
def collect(period, portfolio_name, data_dir):
    """Fetch historical pricing for assets in the database."""
    from src.services.prices import collect_prices
    try:
        result = collect_prices(
            data_dir, period=period, portfolio_name=portfolio_name or None,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Collection complete: {len(result.tickers_collected)} succeeded, "
        f"{len(result.tickers_failed)} failed."
    )
    for ticker, reason in result.tickers_failed.items():
        click.echo(f"  ! {ticker}: {reason}")


@cli.group()
def portfolio():
    """Manage saved portfolios."""
    pass


@portfolio.command("list")
@click.option("--data-dir", default="data", show_default=True,
              help="Data directory to read from (e.g. 'data' or 'data_demo').")
def portfolio_list(data_dir):
    """List all saved portfolios."""
    from src.services.portfolios import list_portfolios
    summaries = list_portfolios(data_dir)
    if not summaries:
        click.echo("No portfolios saved yet.")
        return
    for s in summaries:
        click.echo(f"  {s.name}  ({s.position_count} positions, total cost ${s.total_cost:,.2f})")


@portfolio.command("create")
@click.argument("name")
@click.option("--data-dir", default="data", show_default=True)
def portfolio_create(name, data_dir):
    """Create an empty portfolio. Add positions later via trades or CSV."""
    from src.services.portfolios import create_portfolio
    try:
        create_portfolio(data_dir, name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created empty portfolio '{name}'.")


@portfolio.command("delete")
@click.argument("name")
@click.option("--data-dir", default="data", show_default=True)
def portfolio_delete(name, data_dir):
    """Delete a saved portfolio."""
    from src.services.portfolios import delete_portfolio
    try:
        delete_portfolio(data_dir, name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Deleted portfolio '{name}'.")


@cli.group()
def demo():
    """Manage the demo dataset in data_demo/ (separate from live data/)."""
    pass


@demo.command("seed")
@click.option("--reset", is_flag=True, help="Wipe data_demo/ before seeding.")
def demo_seed(reset):
    """Populate data_demo/ with sample portfolios for screen-sharing."""
    from src import demo as demo_data
    if reset:
        demo_data.reset()
    db = demo_data.seed()
    click.echo(f"Seeded {demo_data.DEMO_DATA_DIR}/ → portfolios: {db.list_portfolios()}")


@demo.command("reset")
def demo_reset():
    """Delete the data_demo/ directory entirely."""
    from src import demo as demo_data
    demo_data.reset()
    click.echo(f"Removed {demo_data.DEMO_DATA_DIR}/.")


@cli.group()
def summaries():
    """Manage stored summaries of past agent conversations."""
    pass


@summaries.command("list")
@click.option("--agent", default=None,
              help="Filter to one agent (risk / wealth / research / pm / cio).")
@click.option("--data-dir", default="data", show_default=True)
def summaries_list(agent, data_dir):
    """Show all saved agent-conversation summaries, newest first."""
    from src.services.summaries import list_summaries
    items = list_summaries(data_dir, agent=agent)
    if not items:
        click.echo("No summaries stored." + (f" (filter: agent={agent})" if agent else ""))
        return
    rows = [{
        "key":     s.key,
        "agent":   s.agent,
        "started": s.started_at,
        "msgs":    s.message_count,
        "preview": (s.summary or "")[:60].replace("\n", " ") + "…",
    } for s in items]
    click.echo(tabulate(rows, headers="keys", tablefmt="github"))


@summaries.command("show")
@click.argument("key")
@click.option("--data-dir", default="data", show_default=True)
def summaries_show(key, data_dir):
    """Print one summary in full."""
    from src.services.summaries import get_summary
    try:
        s = get_summary(data_dir, key)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"agent      : {s.agent}")
    click.echo(f"started_at : {s.started_at}")
    click.echo(f"messages   : {s.message_count}")
    click.echo()
    click.echo("=== SUMMARY ===")
    click.echo(s.summary or "(empty)")


@summaries.command("delete")
@click.argument("key")
@click.option("--data-dir", default="data", show_default=True)
def summaries_delete(key, data_dir):
    """Delete a stored summary."""
    from src.services.summaries import delete_summary
    try:
        delete_summary(data_dir, key)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Deleted '{key}'.")


@cli.group()
def group():
    """Manage portfolio groups (e.g. Taxable, Tax-Free, Retirement)."""
    pass


@group.command("list")
@click.option("--data-dir", default="data", show_default=True)
def group_list(data_dir):
    """List all groups + their members."""
    from src.services.groups import list_groups
    infos = list_groups(data_dir)
    if not infos:
        click.echo("No groups defined.")
        return
    for info in infos:
        click.echo(f"\n{info.name}" + (f"  — {info.description}" if info.description else ""))
        members = info.members
        click.echo(f"  Members ({info.member_count}): {', '.join(members) if members else '—'}")


@group.command("create")
@click.argument("name")
@click.option("--description", default="", help="Optional description for the group.")
@click.option("--data-dir", default="data", show_default=True)
def group_create(name, description, data_dir):
    """Create (or update the description of) a group."""
    from src.services.groups import create_group
    try:
        create_group(data_dir, name, description=description)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Group '{name}' ready.")


@group.command("add")
@click.argument("group_name")
@click.argument("portfolio_name")
@click.option("--data-dir", default="data", show_default=True)
def group_add(group_name, portfolio_name, data_dir):
    """Add a portfolio to a group."""
    from src.services.groups import add_to_group
    try:
        add_to_group(data_dir, group_name, portfolio_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Added '{portfolio_name}' to '{group_name}'.")


@group.command("remove")
@click.argument("group_name")
@click.argument("portfolio_name")
@click.option("--data-dir", default="data", show_default=True)
def group_remove(group_name, portfolio_name, data_dir):
    """Remove a portfolio from a group."""
    from src.services.groups import remove_from_group
    try:
        remove_from_group(data_dir, group_name, portfolio_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Removed '{portfolio_name}' from '{group_name}'.")


@group.command("delete")
@click.argument("name")
@click.option("--data-dir", default="data", show_default=True)
def group_delete(name, data_dir):
    """Delete a group and clear all its memberships (portfolios are untouched)."""
    from src.services.groups import delete_group
    try:
        delete_group(data_dir, name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Deleted group '{name}'.")


@group.command("show")
@click.argument("portfolio_name")
@click.option("--data-dir", default="data", show_default=True)
def group_show(portfolio_name, data_dir):
    """Show which groups a portfolio belongs to."""
    from src.services.groups import get_groups_for_portfolio
    try:
        groups = get_groups_for_portfolio(data_dir, portfolio_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not groups:
        click.echo(f"'{portfolio_name}' is not in any group.")
    else:
        click.echo(f"'{portfolio_name}' is in: {', '.join(groups)}")


@cli.group()
def benchmarks():
    """Named benchmark portfolios (60/40, All Seasons, Golden Butterfly, …)."""
    pass


@benchmarks.command("list")
def benchmarks_list():
    """Print every benchmark + its proxy weights."""
    from src.benchmarks import BENCHMARKS
    for name, b in BENCHMARKS.items():
        click.echo(f"\n{name}")
        click.echo("  " + b.description)
        rows = [{"ticker": t, "weight": f"{w:.2%}"} for t, w in b.weights.items()]
        click.echo(tabulate(rows, headers="keys", tablefmt="github"))


@benchmarks.command("fetch")
@click.option("--period", default="10y",
              help="yfinance period to pull for each proxy (default 10y).")
@click.option("--data-dir", default="data", show_default=True)
def benchmarks_fetch(period, data_dir):
    """Pull price history for every benchmark proxy via yfinance."""
    from src.benchmarks import all_proxy_tickers
    from src.services.prices import collect_prices
    tickers = all_proxy_tickers()
    click.echo(f"Fetching prices for {len(tickers)} proxy tickers: {', '.join(tickers)}")
    result = collect_prices(data_dir, period=period, tickers=tickers)
    click.echo(
        f"Done. Collected {len(result.tickers_collected)}, "
        f"failed {len(result.tickers_failed)}."
    )
    for t, reason in result.tickers_failed.items():
        click.echo(f"  ! {t}: {reason}")


@cli.group()
def metrics():
    """Compute & persist daily returns / risk / attribution time series."""
    pass


@cli.group()
def production():
    """Run / monitor the scheduled analytics-production jobs."""
    pass


@production.command("status")
@click.option("--data-dir", default="data", show_default=True)
def production_status(data_dir):
    """Show each job's last run, status, and whether it's due."""
    from src.services.production import list_jobs
    rows = []
    for j in list_jobs(data_dir):
        rows.append({
            "job":         j.job_name,
            "enabled":     "yes" if j.enabled else "no",
            "interval_h":  round(j.interval_minutes / 60, 1),
            "last_run":    j.last_run_at.strftime("%Y-%m-%d %H:%M") if j.last_run_at else "—",
            "last_status": j.last_status or "—",
            "due":         "yes" if j.is_due else "no",
        })
    click.echo(tabulate(rows, headers="keys", tablefmt="github"))


@production.command("run")
@click.option("--data-dir", default="data", show_default=True)
def production_run(data_dir):
    """Run every job that's currently due. Cron-friendly one-shot."""
    from src.services.production import run_due_jobs
    resp = run_due_jobs(data_dir)
    if not resp.results:
        click.echo("No jobs were due.")
        return
    for r in resp.results:
        click.echo(
            f"[{r.status:7}] {r.job_name:24}  {r.duration_seconds:.2f}s"
            + (f"  — {r.error}" if r.status == "error" else "")
        )


@production.command("run-now")
@click.argument("job_name")
@click.option("--data-dir", default="data", show_default=True)
def production_run_now(job_name, data_dir):
    """Force-run one job ignoring schedule + enabled flag."""
    from src.services.production import run_job
    try:
        r = run_job(data_dir, job_name, force=True)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"[{r.status}] {job_name}  {r.duration_seconds:.2f}s"
        + (f"\n{r.error}" if r.status == "error" else "")
    )


@production.command("daemon")
@click.option("--check-every", default=60, type=int,
              help="Seconds between schedule checks (default 60).")
def production_daemon(check_every):
    """Long-running loop: check the schedule every N seconds and run due jobs."""
    from src.production import JobRunner
    click.echo(f"Production daemon started; checking every {check_every}s. Ctrl-C to stop.")
    JobRunner(Database()).daemon(check_every_seconds=check_every)


@production.group()
def schedule():
    """Manage systemd user timers for production jobs."""
    pass


@schedule.command("list")
def schedule_list():
    """Show systemd-timer status for every registered job."""
    from src import scheduler as _sched
    if not _sched.is_systemd_available():
        raise click.ClickException(
            "systemd --user is not available on this system."
        )
    rows = []
    for name, st_ in _sched.list_scheduled().items():
        rows.append({
            "job":       name,
            "installed": "yes" if st_.get("installed") else "no",
            "active":    st_.get("active_raw", "—"),
            "enabled":   st_.get("enabled_raw", "—"),
            "next_run":  st_.get("next_run") or "—",
        })
    click.echo(tabulate(rows, headers="keys", tablefmt="github"))


@schedule.command("install")
@click.argument("job_name")
@click.option("--interval", default=None, type=int,
              help="Override the job's configured interval (minutes).")
def schedule_install(job_name, interval):
    """Install + enable a user systemd timer for one job."""
    from src import scheduler as _sched
    from src.production import JOB_REGISTRY
    if job_name not in JOB_REGISTRY:
        raise click.ClickException(
            f"Unknown job '{job_name}'. Known: {', '.join(JOB_REGISTRY)}"
        )
    if interval is None:
        from src.services.production import get_job
        try:
            interval = int(get_job("data", job_name).interval_minutes)
        except ValueError:
            interval = int(JOB_REGISTRY[job_name]["interval_minutes"])
    res = _sched.install(job_name, interval)
    if not res["ok"]:
        raise click.ClickException(res["detail"])
    click.echo(res["detail"])


@schedule.command("uninstall")
@click.argument("job_name")
def schedule_uninstall(job_name):
    """Disable + remove the user systemd timer for one job."""
    from src import scheduler as _sched
    res = _sched.uninstall(job_name)
    if not res["ok"]:
        raise click.ClickException(res["detail"])
    click.echo(res["detail"])


@metrics.command("refresh")
@click.option("--portfolio", "portfolio_name", default=None,
              help="Refresh only this portfolio (default: all).")
@click.option("--from", "start_date", default=None,
              help="Recompute from this date onward (YYYY-MM-DD).")
@click.option("--full", is_flag=True, help="Recompute the full history (ignore incremental).")
@click.option("--data-dir", default="data", show_default=True)
def metrics_refresh(portfolio_name, start_date, full, data_dir):
    """Compute daily security / portfolio / attribution metrics and save to parquet."""
    from src.services.production import refresh_metrics
    from src.services.schemas.production import MetricsRefreshRequest
    summary = refresh_metrics(
        data_dir,
        MetricsRefreshRequest(portfolio_name=portfolio_name, start_date=start_date, full=full),
    ).summary
    click.echo(
        f"Refreshed metrics — security: {summary.get('security_rows', 0)} rows, "
        f"portfolio: {summary.get('portfolio_rows', 0)} rows, "
        f"attribution: {summary.get('attribution_rows', 0)} rows "
        f"(portfolios: {', '.join(summary.get('portfolios') or [])})"
    )


@cli.command()
@click.argument("name")
@click.option("--data-dir", default="data", show_default=True)
def report(name, data_dir):
    """Generate risk and exposure reports for a saved portfolio."""
    from src.services.reports import (
        covariance_to_dataframe,
        exposure as service_exposure,
        risk_metrics as service_risk_metrics,
    )

    try:
        exposure_report = service_exposure(data_dir, name)
        risk_report = service_risk_metrics(data_dir, name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"\n--- {exposure_report.portfolio_name} — Exposure Report ---")
    exposure_rows = [
        {"asset_type": r.asset_type, "sector": r.sector or "—",
         "market_value": round(r.market_value, 2), "weight_pct": round(r.weight_pct, 2)}
        for r in exposure_report.rows
    ]
    click.echo(tabulate(exposure_rows, headers="keys", tablefmt="grid"))

    click.echo(f"\n--- {risk_report.portfolio_name} — Risk Metrics ---")
    click.echo(f"Volatility: {risk_report.annualised_volatility:.4f}")
    click.echo(f"Historical VaR (95%): {risk_report.historical_var_95:.4f}")
    click.echo(f"Monte Carlo VaR (95%): {risk_report.monte_carlo_var_95:.4f}")
    cov_df = covariance_to_dataframe(risk_report)
    if not cov_df.empty:
        click.echo("\nCovariance Matrix:")
        click.echo(tabulate(cov_df, headers="keys", tablefmt="grid"))


@cli.command()
@click.option("--portfolio", "portfolio_name", default=None,
              help="Start with a risk assessment of this portfolio.")
@click.option("--query", default=None,
              help="Run a single query and exit (non-interactive).")
def agent(portfolio_name, query):
    """Chat with the risk management agent powered by Claude Opus 4.6.

    Launches an interactive session by default. Use --query for a single
    one-shot question. Use --portfolio to open with an automatic risk
    assessment of the named portfolio.

    Examples:\n
      invest-monitor agent --portfolio "My Portfolio"\n
      invest-monitor agent --query "Which of my portfolios has the highest VaR?"
    """
    agent_instance = RiskAgent()

    if query:
        if portfolio_name:
            full_query = f"Regarding the '{portfolio_name}' portfolio: {query}"
        else:
            full_query = query
        click.echo(agent_instance.run_query(full_query))
    else:
        agent_instance.run_interactive(initial_portfolio=portfolio_name)


@cli.command()
@click.option("--portfolio", "portfolio_name", default=None,
              help="Open with a full wealth overview of this portfolio.")
@click.option("--query", default=None,
              help="Run a single query and exit (non-interactive).")
def wealth(portfolio_name, query):
    """Chat with the wealth management agent powered by Claude Opus 4.6.

    Covers portfolio value, total return, diversification scoring,
    rebalancing, goal projection, allocation optimisation, and
    tax-loss harvesting.

    Examples:\n
      invest-monitor wealth --portfolio "My Portfolio"\n
      invest-monitor wealth --query "Am I on track to reach $500k in 10 years?"\n
      invest-monitor wealth --portfolio "My Portfolio" --query "Optimise my allocation"
    """
    agent_instance = WealthAgent()

    if query:
        full_query = (
            f"Regarding the '{portfolio_name}' portfolio: {query}"
            if portfolio_name else query
        )
        click.echo(agent_instance.run_query(full_query))
    else:
        agent_instance.run_interactive(initial_portfolio=portfolio_name)


@cli.command()
@click.option("--portfolio", "portfolio_name", default=None,
              help="Open with a baseline analysis of this portfolio.")
@click.option("--query", default=None,
              help="Run a single research query and exit (non-interactive).")
def research(portfolio_name, query):
    """Research new investments using web search and portfolio simulation.

    The agent searches the web for candidates, vets them against your
    existing portfolio constraints (sector exposure, VaR, max drawdown),
    and simulates the impact of proposed allocations.

    Examples:\n
      invest-monitor research --portfolio "My Portfolio"\n
      invest-monitor research --query "How can I deploy $100k without increasing software sector exposure or VaR?"\n
      invest-monitor research --portfolio "My Portfolio" --query "Find me bond ETFs that reduce my overall drawdown"
    """
    agent_instance = ResearchAgent()

    if query:
        full_query = (
            f"Regarding the '{portfolio_name}' portfolio: {query}"
            if portfolio_name else query
        )
        click.echo(agent_instance.run_query(full_query))
    else:
        agent_instance.run_interactive(initial_portfolio=portfolio_name)


@cli.command()
@click.option("--portfolio", "portfolio_name", default=None,
              help="Open with a snapshot of this portfolio's positions.")
@click.option("--query", default=None,
              help="Run a single query and exit (non-interactive).")
def pm(portfolio_name, query):
    """Chat with the Portfolio Manager agent powered by Claude Opus 4.6.

    Builds and refines concrete trade proposals: target allocations,
    BUY/SELL orders with dollar amounts and share counts, sector-tilt
    projections, and a structured proposal record for hand-off to the CIO.

    Examples:\n
      invest-monitor pm --portfolio "My Portfolio"\n
      invest-monitor pm --query "Propose a 60/40 deployment of $50k into BND and VTI"\n
      invest-monitor pm --portfolio "My Portfolio" --query "Rebalance to equal-weight across all current holdings"
    """
    agent_instance = PortfolioManagerAgent()

    if query:
        full_query = (
            f"Regarding the '{portfolio_name}' portfolio: {query}"
            if portfolio_name else query
        )
        click.echo(agent_instance.run_query(full_query))
    else:
        agent_instance.run_interactive(initial_portfolio=portfolio_name)


@cli.command()
@click.option("--portfolio", "portfolio_name", default=None,
              help="Open with a holistic CIO view of this portfolio.")
@click.option("--query", default=None,
              help="Run a single query and exit (non-interactive).")
def cio(portfolio_name, query):
    """Chat with the CIO agent powered by Claude Opus 4.6.

    Holistic oversight: reviews proposals against firm-level concentration
    and sector caps, and produces a structured decision — approve,
    override, or request more research.

    Examples:\n
      invest-monitor cio --portfolio "My Portfolio"\n
      invest-monitor cio --query "Review this proposal: deploy $25k as {AAPL: 0.5, MSFT: 0.5}"\n
      invest-monitor cio --portfolio "My Portfolio" --query "What's our biggest concentration risk right now?"
    """
    agent_instance = CIOAgent()

    if query:
        full_query = (
            f"Regarding the '{portfolio_name}' portfolio: {query}"
            if portfolio_name else query
        )
        click.echo(agent_instance.run_query(full_query))
    else:
        agent_instance.run_interactive(initial_portfolio=portfolio_name)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Interface to bind. Use 0.0.0.0 to listen on all interfaces.")
@click.option("--port", default=8000, type=int, show_default=True)
@click.option("--data-dir", default=None,
              help="Set INVEST_MONITOR_DATA_DIR for the server process. "
                   "Per-request X-Data-Dir headers still override.")
@click.option("--reload", is_flag=True, help="Enable uvicorn auto-reload (development).")
def serve(host, port, data_dir, reload):
    """Run the invest-monitor HTTP API (FastAPI + uvicorn).

    All read/write traffic from future frontends goes through this server.
    Streamlit can also call into the same service layer in-process — it
    does not need this server to be running.
    """
    import os
    import uvicorn
    if data_dir:
        os.environ["INVEST_MONITOR_DATA_DIR"] = data_dir
    uvicorn.run("src.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()

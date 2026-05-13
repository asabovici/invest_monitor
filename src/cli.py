import click
from tabulate import tabulate

from src import env as _env  # noqa: F401  — loads .env into os.environ
from src.database import Database
from src.collector import Collector
from src.data.ingestion import Ingester
from src.reporting import ReportingEngine
from src.agent import RiskAgent, WealthAgent, ResearchAgent


@click.group()
def cli():
    pass


@cli.command()
@click.argument("csv_path")
@click.option("--name", default="", help="Portfolio name (defaults to CSV filename)")
def load(csv_path, name):
    """Load a portfolio from a CSV file and save it to the database."""
    db = Database()
    portfolio = Ingester(db).load_portfolio_from_csv(csv_path, name)
    click.echo(f"Saved portfolio '{portfolio.name}' with {len(portfolio.positions)} positions.")


@cli.command()
@click.option("--period", default="1y", help="Collection period (e.g. 1y, 1mo)")
@click.option("--portfolio", "portfolio_name", default="", help="Collect only for a specific portfolio")
def collect(period, portfolio_name):
    """Fetch historical pricing for assets in the database."""
    db = Database()
    if portfolio_name:
        portfolio = db.get_portfolio(portfolio_name)
        tickers = [pos.asset.ticker for pos in portfolio.positions]
        Collector(db).collect_prices(tickers, period=period)
    else:
        Collector(db).update_all_assets(period=period)
    click.echo("Collection complete.")


@cli.group()
def portfolio():
    """Manage saved portfolios."""
    pass


@portfolio.command("list")
def portfolio_list():
    """List all saved portfolios."""
    db = Database()
    names = db.list_portfolios()
    if not names:
        click.echo("No portfolios saved yet.")
    else:
        for name in names:
            click.echo(f"  {name}")


@portfolio.command("create")
@click.argument("name")
def portfolio_create(name):
    """Create an empty portfolio. Add positions later via trades or CSV."""
    from src.models import Portfolio
    db = Database()
    if name in db.list_portfolios():
        raise click.ClickException(f"Portfolio '{name}' already exists.")
    db.save_portfolio(Portfolio(name=name, positions=[]))
    click.echo(f"Created empty portfolio '{name}'.")


@portfolio.command("delete")
@click.argument("name")
def portfolio_delete(name):
    """Delete a saved portfolio."""
    db = Database()
    db.delete_portfolio(name)
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
def metrics():
    """Compute & persist daily returns / risk / attribution time series."""
    pass


@cli.group()
def production():
    """Run / monitor the scheduled analytics-production jobs."""
    pass


@production.command("status")
def production_status():
    """Show each job's last run, status, and whether it's due."""
    import pandas as pd
    from src.production import JobRunner
    runner = JobRunner(Database())
    jobs = runner.db.get_production_jobs().sort_values("job_name")
    now = pd.Timestamp.now()
    rows = []
    for _, r in jobs.iterrows():
        last_run = r["last_run_at"]
        rows.append({
            "job":         r["job_name"],
            "enabled":     "yes" if bool(r["enabled"]) else "no",
            "interval_h":  round(int(r["interval_minutes"]) / 60, 1),
            "last_run":    last_run.strftime("%Y-%m-%d %H:%M") if pd.notna(last_run) else "—",
            "last_status": r["last_status"] or "—",
            "due":         "yes" if runner.is_due(r, now=now) else "no",
        })
    click.echo(tabulate(rows, headers="keys", tablefmt="github"))


@production.command("run")
def production_run():
    """Run every job that's currently due. Cron-friendly one-shot."""
    from src.production import JobRunner
    runner = JobRunner(Database())
    results = runner.run_due_jobs()
    if not results:
        click.echo("No jobs were due.")
        return
    for r in results:
        click.echo(f"[{r['status']:7}] {r['job_name']:24}  {r.get('duration_seconds', 0):.2f}s"
                   + (f"  — {r.get('error')}" if r['status'] == 'error' else ""))


@production.command("run-now")
@click.argument("job_name")
def production_run_now(job_name):
    """Force-run one job ignoring schedule + enabled flag."""
    from src.production import JobRunner, JOB_REGISTRY
    if job_name not in JOB_REGISTRY:
        raise click.ClickException(
            f"Unknown job '{job_name}'. Known: {', '.join(JOB_REGISTRY)}"
        )
    runner = JobRunner(Database())
    r = runner.run_job(job_name, force=True)
    click.echo(
        f"[{r['status']}] {job_name}  {r.get('duration_seconds', 0):.2f}s"
        + (f"\n{r.get('error')}" if r['status'] == 'error' else "")
    )


@production.command("daemon")
@click.option("--check-every", default=60, type=int,
              help="Seconds between schedule checks (default 60).")
def production_daemon(check_every):
    """Long-running loop: check the schedule every N seconds and run due jobs."""
    from src.production import JobRunner
    click.echo(f"Production daemon started; checking every {check_every}s. Ctrl-C to stop.")
    JobRunner(Database()).daemon(check_every_seconds=check_every)


@metrics.command("refresh")
@click.option("--portfolio", "portfolio_name", default=None,
              help="Refresh only this portfolio (default: all).")
@click.option("--from", "start_date", default=None,
              help="Recompute from this date onward (YYYY-MM-DD).")
@click.option("--full", is_flag=True, help="Recompute the full history (ignore incremental).")
def metrics_refresh(portfolio_name, start_date, full):
    """Compute daily security / portfolio / attribution metrics and save to parquet."""
    from src.attribution import AttributionEngine
    db = Database()
    summary = AttributionEngine(db).refresh_all(
        start_date=start_date, portfolio_name=portfolio_name, full=full,
    )
    click.echo(
        f"Refreshed metrics — security: {summary['security_rows']} rows, "
        f"portfolio: {summary['portfolio_rows']} rows, "
        f"attribution: {summary['attribution_rows']} rows "
        f"(portfolios: {', '.join(summary['portfolios'])})"
    )


@cli.command()
@click.argument("name")
def report(name):
    """Generate risk and exposure reports for a saved portfolio."""
    db = Database()
    portfolio = db.get_portfolio(name)
    engine = ReportingEngine(db)

    click.echo(f"\n--- {portfolio.name} — Exposure Report ---")
    exposure = engine.get_portfolio_exposure(portfolio)
    click.echo(tabulate(exposure, headers="keys", tablefmt="grid"))

    click.echo(f"\n--- {portfolio.name} — Risk Metrics ---")
    metrics = engine.get_portfolio_risk_metrics(portfolio)
    for k, v in metrics.items():
        if k == "Covariance Matrix":
            click.echo(f"\n{k}:")
            click.echo(tabulate(v, headers="keys", tablefmt="grid"))
        else:
            click.echo(f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}")


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


if __name__ == "__main__":
    cli()

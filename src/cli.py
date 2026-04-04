import click
from tabulate import tabulate

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


@portfolio.command("delete")
@click.argument("name")
def portfolio_delete(name):
    """Delete a saved portfolio."""
    db = Database()
    db.delete_portfolio(name)
    click.echo(f"Deleted portfolio '{name}'.")


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

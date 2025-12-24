import click
from src.database import Database
from src.collector import Collector
from src.ingestion import Ingester
from src.reporting import ReportingEngine
from tabulate import tabulate

@click.group()
def cli():
    pass

@cli.command()
@click.argument('csv_path')
@click.option('--name', default='Main Portfolio', help='Portfolio name')
def load(csv_path, name):
    """Load a portfolio from a CSV file."""
    db = Database()
    ingester = Ingester(db)
    portfolio = ingester.load_portfolio_from_csv(csv_path, name)
    click.echo(f"Loaded portfolio '{name}' with {len(portfolio.positions)} positions.")

@cli.command()
@click.option('--period', default='1y', help='Collection period (e.g., 1y, 1mo)')
def collect(period):
    """Fetch daily pricing for all assets in the database."""
    db = Database()
    collector = Collector(db)
    collector.update_all_assets(period=period)
    click.echo("Collection complete.")

@cli.command()
@click.argument('csv_path')  # We pass CSV path again to reconstruct the portfolio object for now
def report(csv_path):
    """Generate risk and exposure reports."""
    db = Database()
    ingester = Ingester(db)
    portfolio = ingester.load_portfolio_from_csv(csv_path, "Report Portfolio")
    engine = ReportingEngine(db)
    
    click.echo("\n--- Exposure Report ---")
    exposure = engine.get_portfolio_exposure(portfolio)
    click.echo(tabulate(exposure, headers='keys', tablefmt='grid'))
    
    click.echo("\n--- Risk Metrics ---")
    metrics = engine.get_portfolio_risk_metrics(portfolio)
    for k, v in metrics.items():
        if k == "Covariance Matrix":
            click.echo(f"\n{k}:")
            click.echo(tabulate(v, headers='keys', tablefmt='grid'))
        else:
            click.echo(f"{k}: {v:.4f}" if isinstance(v, float) else f"{k}: {v}")

if __name__ == '__main__':
    cli()

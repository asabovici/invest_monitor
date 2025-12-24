import pandas as pd
import numpy as np
from typing import List, Dict
from src.models import Portfolio, AssetType
from src.database import Database

class ReportingEngine:
    def __init__(self, db: Database):
        self.db = db

    def get_portfolio_exposure(self, portfolio: Portfolio) -> pd.DataFrame:
        """Returns exposure by AssetType, Sector, and Currency."""
        data = []
        for pos in portfolio.positions:
            base_value = pos.quantity * pos.cost_basis  # For exposure we might want current price, but cost basis is a start
            
            # Aggregate based on asset properties
            # If look-through is needed, this would expand the constituents here
            if pos.asset.is_composite():
                for c in pos.asset.constituents:
                    data.append({
                        "Ticker": c.ticker,
                        "Type": "Constituent",
                        "Sector": "Look-through",
                        "Weight": c.weight * base_value
                    })
            else:
                data.append({
                    "Ticker": pos.asset.ticker,
                    "Type": pos.asset.asset_type.value,
                    "Sector": pos.asset.sector,
                    "Weight": base_value
                })
        
        df = pd.DataFrame(data)
        return df.groupby(["Type", "Sector"]).sum()

    def calculate_returns(self, tickers: List[str], start_date: str = None) -> pd.DataFrame:
        prices = self.db.get_historical_prices(tickers, start_date)
        returns = prices.pct_change().dropna()
        return returns

    def calculate_historical_var(self, returns: pd.Series, confidence_level: float = 0.95) -> float:
        """Calculates Historical VaR for a single asset or portfolio returns stream."""
        return np.percentile(returns, (1 - confidence_level) * 100)

    def calculate_monte_carlo_var(self, returns: pd.Series, confidence_level: float = 0.95, 
                                  num_simulations: int = 10000, days: int = 1) -> float:
        """Calculates Monte Carlo VaR."""
        mu = returns.mean()
        sigma = returns.std()
        
        sim_returns = np.random.normal(mu, sigma, num_simulations)
        return np.percentile(sim_returns, (1 - confidence_level) * 100)

    def get_portfolio_risk_metrics(self, portfolio: Portfolio) -> Dict:
        tickers = [p.asset.ticker for p in portfolio.positions]
        returns = self.calculate_returns(tickers)
        
        # Portfolio returns (weighted)
        weights = np.array([p.quantity * p.cost_basis for p in portfolio.positions])
        weights /= weights.sum()
        
        port_returns = returns.dot(weights)
        
        volatility = port_returns.std() * np.sqrt(252)  # Annualized
        hist_var = self.calculate_historical_var(port_returns)
        mc_var = self.calculate_monte_carlo_var(port_returns)
        
        cov_matrix = returns.cov() * 252  # Annualized covariance
        
        return {
            "Volatility": volatility,
            "Historical VaR (95%)": hist_var,
            "Monte Carlo VaR (95%)": mc_var,
            "Covariance Matrix": cov_matrix
        }

    def generate_report(self, portfolio: Portfolio, output_path: str):
        """Generates a Markdown report for the portfolio."""
        exposure = self.get_portfolio_exposure(portfolio)
        risk_metrics = self.get_portfolio_risk_metrics(portfolio)

        with open(output_path, "w") as f:
            f.write(f"# Portfolio Report: {portfolio.name}\n\n")

            f.write("## Holdings\n")
            f.write("| Ticker | Name | Type | Quantity | Cost Basis |\n")
            f.write("|---|---|---|---|---|\n")
            for pos in portfolio.positions:
                f.write(f"| {pos.asset.ticker} | {pos.asset.name} | {pos.asset.asset_type.value} | {pos.quantity} | {pos.cost_basis} |\n")
            f.write("\n")

            f.write("## Exposure Analysis\n")
            f.write(exposure.to_markdown())
            f.write("\n\n")

            f.write("## Risk Metrics\n")
            for k, v in risk_metrics.items():
                if k != "Covariance Matrix":
                    f.write(f"- **{k}**: {v:.4f}\n")

            f.write("\n### Covariance Matrix\n")
            f.write(risk_metrics["Covariance Matrix"].to_markdown())
            f.write("\n")

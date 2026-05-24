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

    def calculate_cumulative_returns(self, tickers: List[str], start_date: str = None) -> pd.DataFrame:
        """Returns cumulative price return series for each ticker, rebased to 0 at start."""
        prices = self.db.get_historical_prices(tickers, start_date)
        if prices.empty:
            return pd.DataFrame()
        first_valid = prices.apply(lambda col: col.dropna().iloc[0] if not col.dropna().empty else np.nan)
        return prices.div(first_valid) - 1

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

    def compute_portfolio_income(
        self,
        portfolio: Portfolio,
        latest_prices: Dict[str, float] = None,
    ) -> pd.DataFrame:
        """Project annual income from each position using income_rate.

        Units of income_rate depend on asset_type:
          • Stock/ETF/Fund: $ per share per PAYMENT
              annual = quantity × rate × payment_frequency
          • Bond/CD/Cash:   annual % of value
              annual = base_value × rate / 100

        Base value uses qty × latest_price, falling back to qty × cost_basis.

        Returns one row per position with columns:
          Ticker, Type, Base Value, Income Rate, Income Rate Unit,
          Annual Income, Monthly Income, Payment Frequency, Yield on Base (%).
        """
        latest_prices = latest_prices or {}
        # Compare on .value rather than the enum member — Streamlit hot-reload
        # can re-import AssetType under a different class identity, which makes
        # `enum_member in (AssetType.X, …)` return False for genuine matches.
        rate_in_dollars_vals = {"Stock", "ETF", "Fund"}
        rows = []
        for pos in portfolio.positions:
            price = latest_prices.get(pos.asset.ticker)
            if price is None or (isinstance(price, float) and np.isnan(price)):
                base_value = pos.quantity * pos.cost_basis
            else:
                base_value = pos.quantity * float(price)
            rate = float(getattr(pos.asset, "income_rate", 0.0) or 0.0)
            freq = int(getattr(pos.asset, "payment_frequency", 1) or 1)

            if pos.asset.asset_type.value in rate_in_dollars_vals:
                annual = pos.quantity * rate * freq
                unit = "$/share/payment"
            else:
                annual = base_value * rate / 100.0
                unit = "%"

            rows.append({
                "Ticker": pos.asset.ticker,
                "Type": pos.asset.asset_type.value,
                "Base Value": base_value,
                "Income Rate": rate,
                "Income Rate Unit": unit,
                "Annual Income": annual,
                "Monthly Income": annual / 12.0,
                "Payment Frequency": freq,
                "Yield on Base (%)": (annual / base_value * 100.0) if base_value else 0.0,
            })
        return pd.DataFrame(rows)

    def compute_sector_stress(
        self,
        portfolio: Portfolio,
        sector_shocks: Dict[str, float],
        non_equity_shocks: Dict[str, float],
        latest_prices: Dict[str, float] = None,
    ) -> pd.DataFrame:
        """One-shot sector-level stress test.

        For each position computes shock_pct by asset type:
          - Stock: sector_shocks[normalize_sector(asset.sector)] (avg fallback)
          - ETF / Fund: blended from fund_profiles.sector_weightings × sector_shocks
            for the stock portion + non_equity_shocks["Bond"] × asset_classes.bondPosition
            for the bond portion (asset_classes also from fund_profiles)
          - Bond / Cash / Crypto: non_equity_shocks[asset_type]

        Returns a DataFrame with one row per position:
          Ticker, Type, Base Value, Shock %, New Value, Change $, Source
        """
        from src.scenarios import normalize_sector

        latest_prices = latest_prices or {}
        avg_sector = (sum(sector_shocks.values()) / len(sector_shocks)) if sector_shocks else 0.0
        rows = []

        for pos in portfolio.positions:
            ticker = pos.asset.ticker
            at = pos.asset.asset_type
            at_val = at.value
            price = latest_prices.get(ticker)
            if price is None or (isinstance(price, float) and np.isnan(price)):
                base_value = pos.quantity * pos.cost_basis
            else:
                base_value = pos.quantity * float(price)

            if at_val in ("ETF", "Fund"):
                profile = self.db.get_fund_profile(ticker)
                asset_classes = profile.get("asset_classes") or {}
                sector_weights = profile.get("sector_weightings") or {}

                stock_w = float(asset_classes.get("stockPosition", 0.0) or 0.0)
                bond_w  = float(asset_classes.get("bondPosition",  0.0) or 0.0)
                cash_w  = float(asset_classes.get("cashPosition",  0.0) or 0.0)
                # Treat preferred/convertible/other as equity-like.
                other_w = max(0.0, 1.0 - stock_w - bond_w - cash_w)
                if stock_w + bond_w + cash_w + other_w == 0:
                    stock_w = 1.0  # no profile data at all → assume 100% equity

                if sector_weights:
                    tot_sw = sum(sector_weights.values())
                    if tot_sw > 0:
                        eq_shock = sum(
                            (w / tot_sw) * sector_shocks.get(normalize_sector(sec) or sec, 0.0)
                            for sec, w in sector_weights.items()
                        )
                        source = f"yfinance: {len(sector_weights)} sectors"
                    else:
                        eq_shock = avg_sector
                        source = "Avg sector (empty weightings)"
                else:
                    eq_shock = avg_sector
                    source = "Avg sector (no profile)"

                bond_shock = non_equity_shocks.get("Bond", 0.0)
                shock_pct = (
                    (stock_w + other_w) * eq_shock
                    + bond_w * bond_shock
                    + cash_w * 0.0
                )

            elif at_val == "Stock":
                sec = normalize_sector(pos.asset.sector)
                if sec and sec in sector_shocks:
                    shock_pct = sector_shocks[sec]
                    source = f"Sector: {sec}"
                else:
                    shock_pct = avg_sector
                    source = f"Avg sector (unknown: {pos.asset.sector or '—'})"

            else:
                # Bond / Cash / CD / Crypto
                shock_pct = non_equity_shocks.get(at.value, 0.0)
                source = at.value

            new_value = base_value * (1 + shock_pct)
            rows.append({
                "Ticker": ticker,
                "Type": at.value,
                "Base Value": base_value,
                "Shock %": shock_pct * 100,
                "New Value": new_value,
                "Change $": new_value - base_value,
                "Source": source,
            })

        return pd.DataFrame(rows)

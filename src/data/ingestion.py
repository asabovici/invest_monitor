import pandas as pd
from src.models import Asset, AssetType, Position, Portfolio, Constituent
from src.database import Database
from typing import List


class Ingester:
    def __init__(self, db: Database):
        self.db = db

    def load_portfolio_from_csv(self, file_path: str, portfolio_name: str = "") -> Portfolio:
        """
        Expected CSV columns: Ticker, Name, Type, Quantity, CostBasis, Currency, Sector
        Optional: ConstituentTickers, ConstituentWeights (comma separated)

        portfolio_name defaults to the CSV filename stem if not provided.
        """
        if not portfolio_name:
            import pathlib
            portfolio_name = pathlib.Path(file_path).stem

        df = pd.read_csv(file_path)
        positions = []

        for _, row in df.iterrows():
            constituents = []
            if pd.notna(row.get("ConstituentTickers")):
                tickers = str(row["ConstituentTickers"]).split(",")
                weights = [float(w) for w in str(row["ConstituentWeights"]).split(",")]
                for t, w in zip(tickers, weights):
                    constituents.append(Constituent(ticker=t.strip(), weight=w))

            asset = Asset(
                ticker=row["Ticker"],
                name=row["Name"],
                asset_type=AssetType(row["Type"]),
                currency=row.get("Currency", "USD"),
                sector=row.get("Sector"),
                constituents=constituents,
            )

            self.db.add_asset(asset)

            positions.append(Position(
                asset=asset,
                quantity=row["Quantity"],
                cost_basis=row["CostBasis"] / row["Quantity"],
            ))

        portfolio = Portfolio(name=portfolio_name, positions=positions)
        self.db.save_portfolio(portfolio)
        return portfolio

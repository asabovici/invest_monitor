import io
import re
from typing import List, Optional

import pandas as pd

from src.database import Database
from src.models import Asset, AssetType, Constituent, Portfolio, Position


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

    # ── ETF / Fund holdings CSV parser ─────────────────────────────────────────

    def parse_fund_holdings_csv(self, content: bytes, fund_ticker: str) -> pd.DataFrame:
        """Parse an ETF/fund holdings CSV from common vendor formats.

        Supported vendor layouts (auto-detected):
          - iShares: header rows before the data table, columns include
            'Ticker', 'Name', 'Weight (%)', 'Sector', 'Asset Class'
          - Vanguard: 'Holdings', 'Shares', '% of fund', 'Sector'
          - Generic: any CSV that has a weight-like column and a name/ticker column

        Returns a normalised DataFrame with columns:
            holding_ticker, holding_name, weight, sector, asset_type
        where weight is a fraction 0–1.
        """
        text = content.decode("utf-8", errors="replace")

        # Strip BOM
        if text.startswith("\ufeff"):
            text = text[1:]

        # Find the first row that looks like a header (has multiple comma-separated tokens
        # and at least one alphabetic word ≥3 chars).
        lines = text.splitlines()
        data_start = 0
        for i, line in enumerate(lines):
            cells = [c.strip().strip('"') for c in line.split(",")]
            alpha_cells = [c for c in cells if re.search(r"[A-Za-z]{3,}", c)]
            if len(cells) >= 3 and len(alpha_cells) >= 2:
                data_start = i
                break

        csv_text = "\n".join(lines[data_start:])
        raw = pd.read_csv(io.StringIO(csv_text), dtype=str)
        raw.columns = [str(c).strip() for c in raw.columns]

        # Drop completely empty rows
        raw = raw.dropna(how="all").reset_index(drop=True)

        col_map = self._detect_holdings_columns(raw.columns.tolist())

        if col_map.get("weight") is None:
            raise ValueError(
                "Could not find a weight column. Expected something like "
                "'Weight (%)', '% of fund', 'Weighting', or 'Weight'."
            )

        df = pd.DataFrame()

        # Ticker
        if col_map.get("ticker"):
            df["holding_ticker"] = raw[col_map["ticker"]].str.strip().str.upper()
        else:
            df["holding_ticker"] = ""

        # Name
        if col_map.get("name"):
            df["holding_name"] = raw[col_map["name"]].str.strip()
        else:
            df["holding_name"] = df["holding_ticker"]

        # Weight — strip % signs, convert to fraction
        raw_weight = raw[col_map["weight"]].str.replace("%", "", regex=False).str.strip()
        df["weight"] = pd.to_numeric(raw_weight, errors="coerce")
        # If weights sum to ~100 treat as percentages, else assume already fractions
        total = df["weight"].sum(skipna=True)
        if total > 1.5:
            df["weight"] = df["weight"] / 100.0

        # Sector
        if col_map.get("sector"):
            df["sector"] = raw[col_map["sector"]].str.strip().fillna("")
        else:
            df["sector"] = ""

        # Asset type
        if col_map.get("asset_type"):
            df["asset_type"] = raw[col_map["asset_type"]].str.strip().fillna("")
        else:
            df["asset_type"] = ""

        # Drop rows with no weight
        df = df[df["weight"].notna() & (df["weight"] > 0)].reset_index(drop=True)

        # Fill blank tickers with a slugified name
        mask_no_ticker = df["holding_ticker"].isna() | (df["holding_ticker"] == "")
        df.loc[mask_no_ticker, "holding_ticker"] = (
            df.loc[mask_no_ticker, "holding_name"]
            .str.upper()
            .str.replace(r"[^A-Z0-9]", "_", regex=True)
            .str[:12]
        )

        return df[["holding_ticker", "holding_name", "weight", "sector", "asset_type"]]

    @staticmethod
    def _detect_holdings_columns(columns: List[str]) -> dict:
        """Return a mapping of logical name → actual column name via fuzzy matching."""
        cols_lower = {c.lower(): c for c in columns}

        def find(candidates):
            for pat in candidates:
                for k, v in cols_lower.items():
                    if pat in k:
                        return v
            return None

        return {
            "ticker": find(["ticker", "symbol", "sedol", "isin"]),
            "name": find(["name", "holding", "description", "security"]),
            "weight": find(["weight", "% of fund", "weighting", "allocation", "% net"]),
            "sector": find(["sector", "industry", "gics"]),
            "asset_type": find(["asset class", "asset_class", "type", "instrument"]),
        }

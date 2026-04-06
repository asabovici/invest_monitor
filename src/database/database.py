import os
import pandas as pd
import duckdb
from typing import List, Optional
from src.models import Asset, AssetType, Constituent, Position, Portfolio

ASSETS_FILE = "assets.parquet"
CONSTITUENTS_FILE = "constituents.parquet"
PORTFOLIOS_FILE = "portfolios.parquet"
POSITIONS_FILE = "positions.parquet"
TRADES_FILE = "trades.parquet"
FUND_HOLDINGS_FILE = "fund_holdings.parquet"
PRICES_DIR = "prices"


class Database:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._init_store()

    def _init_store(self):
        os.makedirs(os.path.join(self.data_dir, PRICES_DIR), exist_ok=True)

        defaults = {
            self._assets_path(): ["ticker", "name", "asset_type", "currency", "sector"],
            self._constituents_path(): ["parent_ticker", "constituent_ticker", "weight"],
            self._portfolios_path(): ["name", "created_at"],
            self._positions_path(): ["portfolio_name", "ticker", "quantity", "cost_basis"],
            self._trades_path(): ["trade_id", "portfolio_name", "ticker", "side", "quantity", "trade_price", "trade_date"],
            self._fund_holdings_path(): ["fund_ticker", "as_of_date", "holding_ticker", "holding_name", "weight", "sector", "asset_type"],
        }
        for path, columns in defaults.items():
            if not os.path.exists(path):
                pd.DataFrame(columns=columns).to_parquet(path, index=False)

    # ── Paths ──────────────────────────────────────────────────────────────────

    def _assets_path(self) -> str:
        return os.path.join(self.data_dir, ASSETS_FILE)

    def _constituents_path(self) -> str:
        return os.path.join(self.data_dir, CONSTITUENTS_FILE)

    def _portfolios_path(self) -> str:
        return os.path.join(self.data_dir, PORTFOLIOS_FILE)

    def _positions_path(self) -> str:
        return os.path.join(self.data_dir, POSITIONS_FILE)

    def _trades_path(self) -> str:
        return os.path.join(self.data_dir, TRADES_FILE)

    def _fund_holdings_path(self) -> str:
        return os.path.join(self.data_dir, FUND_HOLDINGS_FILE)

    def _prices_path(self, ticker: str) -> str:
        return os.path.join(self.data_dir, PRICES_DIR, f"{ticker}.parquet")

    # ── Assets ─────────────────────────────────────────────────────────────────

    def add_asset(self, asset: Asset):
        assets_df = pd.read_parquet(self._assets_path())
        assets_df = assets_df[assets_df["ticker"] != asset.ticker]
        new_row = pd.DataFrame([{
            "ticker": asset.ticker,
            "name": asset.name,
            "asset_type": asset.asset_type.value,
            "currency": asset.currency,
            "sector": asset.sector,
        }])
        pd.concat([assets_df, new_row], ignore_index=True).to_parquet(self._assets_path(), index=False)

        constituents_df = pd.read_parquet(self._constituents_path())
        constituents_df = constituents_df[constituents_df["parent_ticker"] != asset.ticker]
        if asset.constituents:
            new_constituents = pd.DataFrame([{
                "parent_ticker": asset.ticker,
                "constituent_ticker": c.ticker,
                "weight": c.weight,
            } for c in asset.constituents])
            constituents_df = pd.concat([constituents_df, new_constituents], ignore_index=True)
        constituents_df.to_parquet(self._constituents_path(), index=False)

    def get_all_tickers(self) -> List[str]:
        return pd.read_parquet(self._assets_path())["ticker"].tolist()

    # ── Portfolios ─────────────────────────────────────────────────────────────

    def save_portfolio(self, portfolio: Portfolio):
        """Upsert a portfolio and replace all its positions."""
        # Upsert portfolio metadata
        portfolios_df = pd.read_parquet(self._portfolios_path())
        portfolios_df = portfolios_df[portfolios_df["name"] != portfolio.name]
        new_portfolio = pd.DataFrame([{
            "name": portfolio.name,
            "created_at": pd.Timestamp.now().isoformat(),
        }])
        pd.concat([portfolios_df, new_portfolio], ignore_index=True).to_parquet(
            self._portfolios_path(), index=False
        )

        # Replace positions for this portfolio
        positions_df = pd.read_parquet(self._positions_path())
        positions_df = positions_df[positions_df["portfolio_name"] != portfolio.name]
        if portfolio.positions:
            new_positions = pd.DataFrame([{
                "portfolio_name": portfolio.name,
                "ticker": pos.asset.ticker,
                "quantity": pos.quantity,
                "cost_basis": pos.cost_basis,
            } for pos in portfolio.positions])
            positions_df = pd.concat([positions_df, new_positions], ignore_index=True)
        positions_df.to_parquet(self._positions_path(), index=False)

    def list_portfolios(self) -> List[str]:
        """Return names of all saved portfolios."""
        con = duckdb.connect()
        result = con.execute(
            f"SELECT name FROM read_parquet('{self._portfolios_path()}') ORDER BY created_at DESC"
        ).fetchdf()
        return result["name"].tolist()

    def get_portfolio(self, name: str) -> Portfolio:
        """Load a portfolio with full position and asset data via a DuckDB join."""
        con = duckdb.connect()
        rows = con.execute(f"""
            SELECT
                pos.ticker,
                pos.quantity,
                pos.cost_basis,
                a.name        AS asset_name,
                a.asset_type,
                a.currency,
                a.sector
            FROM read_parquet('{self._positions_path()}') pos
            JOIN read_parquet('{self._assets_path()}')    a
              ON pos.ticker = a.ticker
            WHERE pos.portfolio_name = ?
        """, [name]).fetchdf()

        if rows.empty:
            raise ValueError(f"Portfolio '{name}' not found")

        constituents_df = pd.read_parquet(self._constituents_path())

        positions = []
        for _, row in rows.iterrows():
            cons = constituents_df[constituents_df["parent_ticker"] == row["ticker"]]
            asset = Asset(
                ticker=row["ticker"],
                name=row["asset_name"],
                asset_type=AssetType(row["asset_type"]),
                currency=row["currency"],
                sector=row["sector"],
                constituents=[
                    Constituent(ticker=c["constituent_ticker"], weight=c["weight"])
                    for _, c in cons.iterrows()
                ],
            )
            positions.append(Position(asset=asset, quantity=row["quantity"], cost_basis=row["cost_basis"]))

        return Portfolio(name=name, positions=positions)

    def delete_portfolio(self, name: str):
        """Remove a portfolio and all its positions."""
        portfolios_df = pd.read_parquet(self._portfolios_path())
        portfolios_df[portfolios_df["name"] != name].to_parquet(self._portfolios_path(), index=False)

        positions_df = pd.read_parquet(self._positions_path())
        positions_df[positions_df["portfolio_name"] != name].to_parquet(self._positions_path(), index=False)

    # ── Trades ─────────────────────────────────────────────────────────────────

    def record_trade(
        self,
        portfolio_name: str,
        ticker: str,
        side: str,
        quantity: float,
        trade_price: float,
        trade_date: str,
    ) -> None:
        """Append a trade to the ledger and apply it to positions.

        side must be 'BUY' or 'SELL'.  Buys use average-cost blending;
        sells reduce quantity (position removed if quantity reaches zero).
        """
        trades_df = pd.read_parquet(self._trades_path())
        trade_id = int(trades_df["trade_id"].max()) + 1 if not trades_df.empty else 1
        new_row = pd.DataFrame([{
            "trade_id": trade_id,
            "portfolio_name": portfolio_name,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "trade_price": trade_price,
            "trade_date": trade_date,
        }])
        pd.concat([trades_df, new_row], ignore_index=True).to_parquet(self._trades_path(), index=False)
        self._apply_trade_to_positions(portfolio_name, ticker, side, quantity, trade_price)

    def list_trades(self, portfolio_name: Optional[str] = None) -> pd.DataFrame:
        """Return all trades sorted by date descending, optionally filtered by portfolio."""
        df = pd.read_parquet(self._trades_path())
        if portfolio_name:
            df = df[df["portfolio_name"] == portfolio_name]
        return df.sort_values("trade_date", ascending=False).reset_index(drop=True)

    def _apply_trade_to_positions(
        self,
        portfolio_name: str,
        ticker: str,
        side: str,
        quantity: float,
        trade_price: float,
    ) -> None:
        positions_df = pd.read_parquet(self._positions_path())
        mask = (positions_df["portfolio_name"] == portfolio_name) & (positions_df["ticker"] == ticker)
        existing = positions_df[mask]

        if side == "BUY":
            if existing.empty:
                new_pos = pd.DataFrame([{
                    "portfolio_name": portfolio_name,
                    "ticker": ticker,
                    "quantity": quantity,
                    "cost_basis": trade_price,
                }])
                positions_df = pd.concat([positions_df, new_pos], ignore_index=True)
            else:
                old_qty = float(existing["quantity"].iloc[0])
                old_cost = float(existing["cost_basis"].iloc[0])
                new_qty = old_qty + quantity
                new_cost = (old_qty * old_cost + quantity * trade_price) / new_qty
                positions_df.loc[mask, "quantity"] = new_qty
                positions_df.loc[mask, "cost_basis"] = round(new_cost, 6)
        else:  # SELL
            if not existing.empty:
                old_qty = float(existing["quantity"].iloc[0])
                new_qty = old_qty - quantity
                if new_qty <= 1e-8:
                    positions_df = positions_df[~mask]
                else:
                    positions_df.loc[mask, "quantity"] = new_qty

        positions_df.to_parquet(self._positions_path(), index=False)

    def update_positions_direct(self, portfolio_name: str, rows: list[dict]) -> None:
        """Replace positions for a portfolio with the given rows.

        Each row must have keys: ticker, quantity, cost_basis.
        """
        positions_df = pd.read_parquet(self._positions_path())
        positions_df = positions_df[positions_df["portfolio_name"] != portfolio_name]
        if rows:
            new_rows = pd.DataFrame([{
                "portfolio_name": portfolio_name,
                "ticker": r["ticker"],
                "quantity": r["quantity"],
                "cost_basis": r["cost_basis"],
            } for r in rows])
            positions_df = pd.concat([positions_df, new_rows], ignore_index=True)
        positions_df.to_parquet(self._positions_path(), index=False)

    def get_all_assets(self) -> pd.DataFrame:
        """Return the full assets table."""
        df = pd.read_parquet(self._assets_path())
        for col in ("name", "sector", "currency"):
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str)
        return df

    def update_assets_direct(self, assets_df: pd.DataFrame) -> None:
        """Overwrite the assets table with the supplied DataFrame."""
        assets_df.to_parquet(self._assets_path(), index=False)

    # ── Prices ─────────────────────────────────────────────────────────────────

    def save_prices(self, ticker: str, df: pd.DataFrame):
        """df should have a DatetimeIndex and a 'Close' column."""
        new_df = df[["Close"]].copy()
        new_df.index = pd.to_datetime(new_df.index)
        new_df.index.name = "date"
        new_df.columns = ["price"]

        prices_path = self._prices_path(ticker)
        if os.path.exists(prices_path):
            existing = pd.read_parquet(prices_path)
            combined = pd.concat([existing, new_df])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
            combined.to_parquet(prices_path)
        else:
            new_df.sort_index(inplace=True)
            new_df.to_parquet(prices_path)

    # ── Fund holdings (lookthrough) ────────────────────────────────────────────

    def save_fund_holdings(self, fund_ticker: str, as_of_date: str, holdings: pd.DataFrame) -> None:
        """Store a holdings snapshot for a fund/ETF.

        holdings must have columns: holding_ticker, holding_name, weight, sector, asset_type.
        Replaces any existing snapshot for the same (fund_ticker, as_of_date).
        """
        df = pd.read_parquet(self._fund_holdings_path())
        df = df[~((df["fund_ticker"] == fund_ticker) & (df["as_of_date"] == as_of_date))]
        new_rows = holdings.copy()
        new_rows["fund_ticker"] = fund_ticker
        new_rows["as_of_date"] = as_of_date
        new_rows = new_rows[["fund_ticker", "as_of_date", "holding_ticker", "holding_name", "weight", "sector", "asset_type"]]
        pd.concat([df, new_rows], ignore_index=True).to_parquet(self._fund_holdings_path(), index=False)

    def get_fund_holdings(self, fund_ticker: str, as_of_date: Optional[str] = None) -> pd.DataFrame:
        """Return holdings for a fund.  If as_of_date is None, returns the latest snapshot."""
        df = pd.read_parquet(self._fund_holdings_path())
        df = df[df["fund_ticker"] == fund_ticker]
        if df.empty:
            return df
        if as_of_date is None:
            as_of_date = df["as_of_date"].max()
        return df[df["as_of_date"] == as_of_date].reset_index(drop=True)

    def list_fund_holdings_dates(self, fund_ticker: str) -> List[str]:
        """Return all snapshot dates for a fund, newest first."""
        df = pd.read_parquet(self._fund_holdings_path())
        dates = df[df["fund_ticker"] == fund_ticker]["as_of_date"].unique().tolist()
        return sorted(dates, reverse=True)

    def delete_fund_holdings(self, fund_ticker: str, as_of_date: str) -> None:
        """Remove a specific holdings snapshot."""
        df = pd.read_parquet(self._fund_holdings_path())
        df[~((df["fund_ticker"] == fund_ticker) & (df["as_of_date"] == as_of_date))].to_parquet(
            self._fund_holdings_path(), index=False
        )

    def list_funds_with_holdings(self) -> List[str]:
        """Return all fund tickers that have at least one holdings snapshot."""
        df = pd.read_parquet(self._fund_holdings_path())
        return df["fund_ticker"].unique().tolist()

    def get_historical_prices(self, tickers: List[str], start_date: Optional[str] = None) -> pd.DataFrame:
        frames = {}
        missing = []
        for ticker in tickers:
            path = self._prices_path(ticker)
            if not os.path.exists(path):
                missing.append(ticker)
                continue
            ticker_df = pd.read_parquet(path)
            if start_date:
                ticker_df = ticker_df[ticker_df.index >= start_date]
            frames[ticker] = ticker_df["price"]

        if not frames and not missing:
            return pd.DataFrame()

        result = pd.DataFrame(frames)

        # Fill missing tickers with a constant price of 1.0, aligned to the
        # same date index as the tickers that do have data.  If no tickers
        # have data at all, use a single row at today's date.
        if missing:
            if result.empty:
                result = pd.DataFrame(
                    index=pd.DatetimeIndex([pd.Timestamp.today().normalize()])
                )
            for ticker in missing:
                result[ticker] = 1.0

        return result

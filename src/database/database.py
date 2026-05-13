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
FUND_PROFILES_FILE = "fund_profiles.parquet"
SECTOR_BETAS_FILE  = "sector_betas.parquet"
DAILY_SECURITY_METRICS_FILE   = "daily_security_metrics.parquet"
DAILY_PORTFOLIO_METRICS_FILE  = "daily_portfolio_metrics.parquet"
DAILY_ATTRIBUTION_FILE        = "daily_attribution.parquet"
PRODUCTION_JOBS_FILE          = "production_jobs.parquet"
PRODUCTION_RUNS_FILE          = "production_runs.parquet"
PRICES_DIR = "prices"


class Database:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._init_store()

    # Default backfill values for columns added via schema migrations.
    _MIGRATION_DEFAULTS = {"income_rate": 0.0, "payment_frequency": 1}

    def _init_store(self):
        os.makedirs(os.path.join(self.data_dir, PRICES_DIR), exist_ok=True)

        defaults = {
            self._assets_path(): ["ticker", "name", "asset_type", "currency", "sector", "income_rate", "payment_frequency"],
            self._constituents_path(): ["parent_ticker", "constituent_ticker", "weight"],
            self._portfolios_path(): ["name", "created_at"],
            self._positions_path(): ["portfolio_name", "ticker", "quantity", "cost_basis"],
            self._trades_path(): ["trade_id", "portfolio_name", "ticker", "side", "quantity", "trade_price", "trade_date"],
            self._fund_holdings_path(): ["fund_ticker", "as_of_date", "holding_ticker", "holding_name", "weight", "sector", "asset_type"],
            self._fund_profiles_path(): ["fund_ticker", "as_of_date", "category", "key", "weight"],
            self._sector_betas_path(): ["sector_a", "sector_b", "beta", "as_of_date"],
            self._daily_security_metrics_path(): [
                "date", "ticker", "price", "daily_return", "cum_return", "rolling_vol_21d",
            ],
            self._daily_portfolio_metrics_path(): [
                "date", "portfolio_name", "total_value", "daily_return",
                "cum_return", "rolling_vol_21d", "drawdown", "max_drawdown",
            ],
            self._daily_attribution_path(): [
                "date", "portfolio_name", "ticker", "weight",
                "position_return", "contribution_to_return", "asset_type", "sector",
            ],
            self._production_jobs_path(): [
                "job_name", "enabled", "interval_minutes", "last_run_at",
                "last_status", "last_error", "last_duration_seconds",
            ],
            self._production_runs_path(): [
                "run_id", "job_name", "started_at", "ended_at",
                "status", "error_message", "details", "duration_seconds",
            ],
        }
        for path, columns in defaults.items():
            if not os.path.exists(path):
                pd.DataFrame(columns=columns).to_parquet(path, index=False)
            else:
                # Backfill any newly-added columns on existing parquet files.
                df = pd.read_parquet(path)
                missing_cols = [c for c in columns if c not in df.columns]
                if missing_cols:
                    for c in missing_cols:
                        df[c] = self._MIGRATION_DEFAULTS.get(c, None)
                    df.to_parquet(path, index=False)

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

    def _fund_profiles_path(self) -> str:
        return os.path.join(self.data_dir, FUND_PROFILES_FILE)

    def _sector_betas_path(self) -> str:
        return os.path.join(self.data_dir, SECTOR_BETAS_FILE)

    def _daily_security_metrics_path(self) -> str:
        return os.path.join(self.data_dir, DAILY_SECURITY_METRICS_FILE)

    def _daily_portfolio_metrics_path(self) -> str:
        return os.path.join(self.data_dir, DAILY_PORTFOLIO_METRICS_FILE)

    def _daily_attribution_path(self) -> str:
        return os.path.join(self.data_dir, DAILY_ATTRIBUTION_FILE)

    def _production_jobs_path(self) -> str:
        return os.path.join(self.data_dir, PRODUCTION_JOBS_FILE)

    def _production_runs_path(self) -> str:
        return os.path.join(self.data_dir, PRODUCTION_RUNS_FILE)

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
            "income_rate": float(asset.income_rate or 0.0),
            "payment_frequency": int(asset.payment_frequency or 1),
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
        """Load a portfolio with full position and asset data via a DuckDB join.

        Returns an empty Portfolio if the name exists in portfolios.parquet but
        has no positions yet (e.g. just created via the UI).
        """
        portfolios_df = pd.read_parquet(self._portfolios_path())
        if name not in portfolios_df["name"].values:
            raise ValueError(f"Portfolio '{name}' not found")

        con = duckdb.connect()
        rows = con.execute(f"""
            SELECT
                pos.ticker,
                pos.quantity,
                pos.cost_basis,
                a.name        AS asset_name,
                a.asset_type,
                a.currency,
                a.sector,
                a.income_rate,
                a.payment_frequency
            FROM read_parquet('{self._positions_path()}') pos
            JOIN read_parquet('{self._assets_path()}')    a
              ON pos.ticker = a.ticker
            WHERE pos.portfolio_name = ?
        """, [name]).fetchdf()

        if rows.empty:
            return Portfolio(name=name, positions=[])

        constituents_df = pd.read_parquet(self._constituents_path())

        def _clean_str(v, default=None):
            if v is None or pd.isna(v):
                return default
            s = str(v).strip()
            return s if s else default

        def _clean_float(v, default=0.0):
            if v is None or pd.isna(v):
                return default
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        def _clean_int(v, default=1):
            if v is None or pd.isna(v):
                return default
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        positions = []
        for _, row in rows.iterrows():
            cons = constituents_df[constituents_df["parent_ticker"] == row["ticker"]]
            asset = Asset(
                ticker=row["ticker"],
                name=_clean_str(row["asset_name"], default=row["ticker"]),
                asset_type=AssetType(row["asset_type"]),
                currency=_clean_str(row["currency"], default="USD"),
                sector=_clean_str(row["sector"]),
                income_rate=_clean_float(row.get("income_rate"), 0.0),
                payment_frequency=_clean_int(row.get("payment_frequency"), 1),
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
        if "income_rate" in df.columns:
            df["income_rate"] = pd.to_numeric(df["income_rate"], errors="coerce").fillna(0.0)
        else:
            df["income_rate"] = 0.0
        if "payment_frequency" in df.columns:
            df["payment_frequency"] = (
                pd.to_numeric(df["payment_frequency"], errors="coerce").fillna(1).astype(int)
            )
        else:
            df["payment_frequency"] = 1
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

    # ── Fund profiles (asset class + sector weightings) ───────────────────────

    def save_fund_profile(
        self,
        fund_ticker: str,
        as_of_date: str,
        asset_classes: dict,
        sector_weightings: dict,
    ) -> None:
        """Store an aggregate fund profile snapshot from yfinance FundsData.

        asset_classes: dict like {'stockPosition': 0.99, 'bondPosition': 0.0, ...}
        sector_weightings: dict like {'technology': 0.35, 'healthcare': 0.08, ...}

        Replaces any existing profile for the same (fund_ticker, as_of_date).
        """
        df = pd.read_parquet(self._fund_profiles_path())
        df = df[~((df["fund_ticker"] == fund_ticker) & (df["as_of_date"] == as_of_date))]
        rows = []
        for k, v in (asset_classes or {}).items():
            rows.append({
                "fund_ticker": fund_ticker,
                "as_of_date": as_of_date,
                "category": "asset_class",
                "key": k,
                "weight": float(v) if v is not None else 0.0,
            })
        for k, v in (sector_weightings or {}).items():
            rows.append({
                "fund_ticker": fund_ticker,
                "as_of_date": as_of_date,
                "category": "sector",
                "key": k,
                "weight": float(v) if v is not None else 0.0,
            })
        if rows:
            df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        df.to_parquet(self._fund_profiles_path(), index=False)

    def get_fund_profile(self, fund_ticker: str, as_of_date: Optional[str] = None) -> dict:
        """Return {'as_of_date', 'asset_classes', 'sector_weightings'} for a fund.
        If as_of_date is None, returns the latest snapshot.
        Returns empty dicts if no profile exists.
        """
        df = pd.read_parquet(self._fund_profiles_path())
        df = df[df["fund_ticker"] == fund_ticker]
        if df.empty:
            return {"as_of_date": None, "asset_classes": {}, "sector_weightings": {}}
        if as_of_date is None:
            as_of_date = df["as_of_date"].max()
        snap = df[df["as_of_date"] == as_of_date]
        asset_classes = dict(zip(
            snap[snap["category"] == "asset_class"]["key"],
            snap[snap["category"] == "asset_class"]["weight"],
        ))
        sectors = dict(zip(
            snap[snap["category"] == "sector"]["key"],
            snap[snap["category"] == "sector"]["weight"],
        ))
        return {"as_of_date": as_of_date, "asset_classes": asset_classes, "sector_weightings": sectors}

    def list_fund_profile_dates(self, fund_ticker: str) -> List[str]:
        """Return all profile snapshot dates for a fund, newest first."""
        df = pd.read_parquet(self._fund_profiles_path())
        dates = df[df["fund_ticker"] == fund_ticker]["as_of_date"].unique().tolist()
        return sorted(dates, reverse=True)

    def delete_fund_profile(self, fund_ticker: str, as_of_date: str) -> None:
        """Remove a specific profile snapshot."""
        df = pd.read_parquet(self._fund_profiles_path())
        df[~((df["fund_ticker"] == fund_ticker) & (df["as_of_date"] == as_of_date))].to_parquet(
            self._fund_profiles_path(), index=False
        )

    # ── Sector betas ──────────────────────────────────────────────────────────

    def save_sector_betas(self, betas: pd.DataFrame, as_of_date: Optional[str] = None) -> None:
        """Store a pairwise sector-beta snapshot.

        `betas` must have columns: sector_a, sector_b, beta. Replaces any
        existing snapshot for the same as_of_date (default = today).
        """
        if as_of_date is None:
            as_of_date = pd.Timestamp.today().date().isoformat()

        existing = pd.read_parquet(self._sector_betas_path())
        existing = existing[existing["as_of_date"] != as_of_date]

        new_rows = betas[["sector_a", "sector_b", "beta"]].copy()
        new_rows["as_of_date"] = as_of_date
        pd.concat([existing, new_rows], ignore_index=True).to_parquet(
            self._sector_betas_path(), index=False
        )

    def get_sector_betas(self, as_of_date: Optional[str] = None) -> pd.DataFrame:
        """Return sector betas as a long DataFrame (sector_a, sector_b, beta).
        If as_of_date is None, returns the latest snapshot. Empty if none."""
        df = pd.read_parquet(self._sector_betas_path())
        if df.empty:
            return df
        if as_of_date is None:
            as_of_date = df["as_of_date"].max()
        return df[df["as_of_date"] == as_of_date].reset_index(drop=True)

    def list_sector_beta_dates(self) -> List[str]:
        """Return all sector-beta snapshot dates, newest first."""
        df = pd.read_parquet(self._sector_betas_path())
        return sorted(df["as_of_date"].unique().tolist(), reverse=True)

    # ── Daily metrics (returns, risk, attribution) ─────────────────────────────

    @staticmethod
    def _upsert_parquet(path: str, df: pd.DataFrame, key_cols: List[str]) -> None:
        """Drop rows in the existing parquet whose key_cols overlap with df,
        then append df and rewrite. No-op if df is empty."""
        if df is None or df.empty:
            return
        existing = pd.read_parquet(path)
        if not existing.empty:
            # Index both sides on the key tuple for an O(n) anti-join.
            new_keys = pd.MultiIndex.from_frame(df[key_cols])
            old_keys = pd.MultiIndex.from_frame(existing[key_cols])
            existing = existing[~old_keys.isin(new_keys)]
        pd.concat([existing, df], ignore_index=True).to_parquet(path, index=False)

    def save_daily_security_metrics(self, df: pd.DataFrame) -> None:
        """Upsert daily per-ticker metrics keyed on (date, ticker)."""
        self._upsert_parquet(
            self._daily_security_metrics_path(), df, ["date", "ticker"],
        )

    def get_daily_security_metrics(
        self, ticker: Optional[str] = None,
        start_date: Optional[str] = None,
    ) -> pd.DataFrame:
        df = pd.read_parquet(self._daily_security_metrics_path())
        if ticker is not None and not df.empty:
            df = df[df["ticker"] == ticker]
        if start_date is not None and not df.empty:
            df = df[pd.to_datetime(df["date"]) >= pd.to_datetime(start_date)]
        return df.reset_index(drop=True)

    def latest_security_metric_date(self) -> Optional[pd.Timestamp]:
        df = pd.read_parquet(self._daily_security_metrics_path())
        if df.empty:
            return None
        return pd.to_datetime(df["date"]).max()

    def save_daily_portfolio_metrics(self, df: pd.DataFrame) -> None:
        """Upsert daily per-portfolio metrics keyed on (date, portfolio_name)."""
        self._upsert_parquet(
            self._daily_portfolio_metrics_path(), df, ["date", "portfolio_name"],
        )

    def get_daily_portfolio_metrics(
        self, portfolio_name: Optional[str] = None,
        start_date: Optional[str] = None,
    ) -> pd.DataFrame:
        df = pd.read_parquet(self._daily_portfolio_metrics_path())
        if portfolio_name is not None and not df.empty:
            df = df[df["portfolio_name"] == portfolio_name]
        if start_date is not None and not df.empty:
            df = df[pd.to_datetime(df["date"]) >= pd.to_datetime(start_date)]
        return df.reset_index(drop=True)

    def latest_portfolio_metric_date(self, portfolio_name: Optional[str] = None) -> Optional[pd.Timestamp]:
        df = self.get_daily_portfolio_metrics(portfolio_name=portfolio_name)
        if df.empty:
            return None
        return pd.to_datetime(df["date"]).max()

    def save_daily_attribution(self, df: pd.DataFrame) -> None:
        """Upsert daily attribution keyed on (date, portfolio_name, ticker)."""
        self._upsert_parquet(
            self._daily_attribution_path(), df, ["date", "portfolio_name", "ticker"],
        )

    def get_daily_attribution(
        self, portfolio_name: Optional[str] = None,
        start_date: Optional[str] = None,
    ) -> pd.DataFrame:
        df = pd.read_parquet(self._daily_attribution_path())
        if portfolio_name is not None and not df.empty:
            df = df[df["portfolio_name"] == portfolio_name]
        if start_date is not None and not df.empty:
            df = df[pd.to_datetime(df["date"]) >= pd.to_datetime(start_date)]
        return df.reset_index(drop=True)

    # ── Production: scheduled job state + run log ─────────────────────────────

    def get_production_jobs(self) -> pd.DataFrame:
        df = pd.read_parquet(self._production_jobs_path())
        if df.empty:
            return df
        if "enabled" in df.columns:
            df["enabled"] = df["enabled"].fillna(True).astype(bool)
        if "interval_minutes" in df.columns:
            df["interval_minutes"] = (
                pd.to_numeric(df["interval_minutes"], errors="coerce").fillna(0).astype(int)
            )
        if "last_run_at" in df.columns:
            df["last_run_at"] = pd.to_datetime(df["last_run_at"], errors="coerce")
        return df.reset_index(drop=True)

    def upsert_production_job(
        self,
        job_name: str,
        *,
        enabled: Optional[bool] = None,
        interval_minutes: Optional[int] = None,
        last_run_at: Optional[pd.Timestamp] = None,
        last_status: Optional[str] = None,
        last_error: Optional[str] = None,
        last_duration_seconds: Optional[float] = None,
    ) -> None:
        """Upsert a single job row keyed on `job_name`. Only the keyword args
        you pass in are written — `None` means "leave the existing value"."""
        df = self.get_production_jobs()
        # Existing row (if any) — preserve fields we aren't updating.
        if not df.empty and job_name in df["job_name"].values:
            existing = df[df["job_name"] == job_name].iloc[0].to_dict()
            df = df[df["job_name"] != job_name]
        else:
            existing = {
                "job_name": job_name,
                "enabled": True,
                "interval_minutes": 0,
                "last_run_at": pd.NaT,
                "last_status": "never_run",
                "last_error": None,
                "last_duration_seconds": None,
            }

        if enabled              is not None: existing["enabled"]              = bool(enabled)
        if interval_minutes     is not None: existing["interval_minutes"]     = int(interval_minutes)
        if last_run_at          is not None: existing["last_run_at"]          = last_run_at
        if last_status          is not None: existing["last_status"]          = last_status
        if last_error           is not None: existing["last_error"]           = last_error
        if last_duration_seconds is not None: existing["last_duration_seconds"] = float(last_duration_seconds)

        pd.concat([df, pd.DataFrame([existing])], ignore_index=True).to_parquet(
            self._production_jobs_path(), index=False
        )

    def append_production_run(
        self,
        job_name: str,
        started_at: pd.Timestamp,
        ended_at: pd.Timestamp,
        status: str,
        error_message: Optional[str] = None,
        details: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> int:
        """Append a row to the run log. Returns the new run_id."""
        df = pd.read_parquet(self._production_runs_path())
        if df.empty or "run_id" not in df.columns or df["run_id"].dropna().empty:
            run_id = 1
        else:
            run_id = int(df["run_id"].max()) + 1
        row = pd.DataFrame([{
            "run_id":          run_id,
            "job_name":        job_name,
            "started_at":      started_at,
            "ended_at":        ended_at,
            "status":          status,
            "error_message":   error_message,
            "details":         details,
            "duration_seconds": duration_seconds,
        }])
        pd.concat([df, row], ignore_index=True).to_parquet(self._production_runs_path(), index=False)
        return run_id

    def get_production_runs(
        self,
        job_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        df = pd.read_parquet(self._production_runs_path())
        if df.empty:
            return df
        if "started_at" in df.columns:
            df["started_at"] = pd.to_datetime(df["started_at"], errors="coerce")
        if "ended_at" in df.columns:
            df["ended_at"] = pd.to_datetime(df["ended_at"], errors="coerce")
        if job_name is not None:
            df = df[df["job_name"] == job_name]
        if status is not None:
            df = df[df["status"] == status]
        df = df.sort_values("started_at", ascending=False)
        if limit is not None:
            df = df.head(limit)
        return df.reset_index(drop=True)

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
        # have data at all and any missing ticker is cash, synthesize a 1-year
        # daily date range so downstream metrics (pct_change, vol, drawdown)
        # compute cleanly (cash is constant 1.0 USD by definition).  Otherwise
        # fall back to a single row at today's date.
        if missing:
            if result.empty:
                cash_tickers = self._cash_tickers()
                if any(t in cash_tickers for t in missing):
                    end = pd.Timestamp.today().normalize()
                    result = pd.DataFrame(
                        index=pd.date_range(end=end, periods=252, freq="B")
                    )
                else:
                    result = pd.DataFrame(
                        index=pd.DatetimeIndex([pd.Timestamp.today().normalize()])
                    )
            for ticker in missing:
                result[ticker] = 1.0

        return result

    def _cash_tickers(self) -> set[str]:
        """Tickers whose price should be treated as constant 1.0 — i.e. Cash
        and CDs (both held at par)."""
        try:
            assets_df = pd.read_parquet(self._assets_path())
            mask = assets_df["asset_type"].isin(["Cash", "CD"])
            return set(assets_df.loc[mask, "ticker"].tolist())
        except Exception:
            return set()

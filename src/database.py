import duckdb
import pandas as pd
import os
from typing import List, Optional
from src.models import Asset, AssetType, Constituent

class Database:
    def __init__(self, data_dir: str = "data/parquet"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.assets_file = os.path.join(self.data_dir, "assets.parquet")
        self.constituents_file = os.path.join(self.data_dir, "constituents.parquet")
        self.prices_file = os.path.join(self.data_dir, "prices.parquet")
        self._init_db()

    def _init_db(self):
        # We don't need to explicitly create tables like in SQLite.
        # But we can ensure empty parquet files exist with correct schema if we want,
        # or just handle 'file not found' gracefully.
        # For now, we'll handle file creation on first write.
        pass

    def _get_connection(self):
        return duckdb.connect(database=':memory:')

    def add_asset(self, asset: Asset):
        conn = self._get_connection()

        # --- Handle Assets ---
        new_asset_df = pd.DataFrame([{
            "ticker": asset.ticker,
            "name": asset.name,
            "asset_type": asset.asset_type.value,
            "currency": asset.currency,
            "sector": asset.sector
        }])

        if os.path.exists(self.assets_file):
            existing_assets = conn.execute(f"SELECT * FROM '{self.assets_file}'").df()
            # Remove existing entry for this ticker if it exists
            existing_assets = existing_assets[existing_assets['ticker'] != asset.ticker]
            combined_assets = pd.concat([existing_assets, new_asset_df], ignore_index=True)
        else:
            combined_assets = new_asset_df
            
        combined_assets.to_parquet(self.assets_file)

        # --- Handle Constituents ---
        # Prepare new constituents data
        if asset.constituents:
            new_constituents_data = []
            for c in asset.constituents:
                new_constituents_data.append({
                    "parent_ticker": asset.ticker,
                    "constituent_ticker": c.ticker,
                    "weight": c.weight
                })
            new_constituents_df = pd.DataFrame(new_constituents_data)
        else:
            new_constituents_df = pd.DataFrame(columns=["parent_ticker", "constituent_ticker", "weight"])

        if os.path.exists(self.constituents_file):
            existing_constituents = conn.execute(f"SELECT * FROM '{self.constituents_file}'").df()
            # Remove existing constituents for this parent_ticker
            existing_constituents = existing_constituents[existing_constituents['parent_ticker'] != asset.ticker]
            if not new_constituents_df.empty:
                combined_constituents = pd.concat([existing_constituents, new_constituents_df], ignore_index=True)
            else:
                combined_constituents = existing_constituents
        else:
            combined_constituents = new_constituents_df

        if not combined_constituents.empty:
            combined_constituents.to_parquet(self.constituents_file)

    def save_prices(self, ticker: str, df: pd.DataFrame):
        """df should have 'Date' index and 'Close' column (and others likely)"""
        # Prepare new data
        # Ensure df has 'ticker' column and 'date' column
        data = df.copy()
        data['ticker'] = ticker
        data['date'] = data.index
        # Keep only necessary columns if needed, but for now we take what we need
        # We need ticker, date, price. Assuming 'Close' is the price.
        # But yfinance might return MultiIndex or different columns.
        # Typically it has 'Close'.

        if 'Close' in data.columns:
            data['price'] = data['Close']
        else:
            # Fallback or error?
            pass

        data = data[['ticker', 'date', 'price']]
        data['date'] = data['date'].dt.strftime('%Y-%m-%d') # consistent string format or use timestamp

        conn = self._get_connection()

        if os.path.exists(self.prices_file):
            # Optimisation: Filter out this ticker's data first? Or just append and then deduplicate?
            # Deduplication on read is easier for "storage", but "save_prices" implies state update.
            # Let's read, remove old data for this ticker (or this ticker+date range), and write back.
            # Since prices can be large, this is inefficient for a real production system but fine for this demo.

            existing_prices = conn.execute(f"SELECT * FROM '{self.prices_file}'").df()

            # Ensure date column is string to match new data
            if not existing_prices.empty and 'date' in existing_prices.columns:
                 existing_prices['date'] = existing_prices['date'].astype(str)

            # Remove existing data for this ticker to overwrite with new data
            # Or merge? Usually we fetch a range. If we fetch 1y, we overwrite last 1y.
            # Simpler approach: Remove all data for this ticker and replace with new set (assuming new set is the "master" for that ticker).
            # But if we collected 5 years before and now collect 1 year, we lose 4 years.
            # Better: Upsert based on Date.

            # Using pandas combine_first or similar?
            # Let's just append and then drop duplicates keeping last.

            combined = pd.concat([existing_prices, data])
            # Drop duplicates on ticker, date, keep last
            combined = combined.drop_duplicates(subset=['ticker', 'date'], keep='last')
            combined.to_parquet(self.prices_file, index=False)
        else:
            data.to_parquet(self.prices_file, index=False)

    def get_historical_prices(self, tickers: List[str], start_date: str = None) -> pd.DataFrame:
        if not os.path.exists(self.prices_file):
            return pd.DataFrame()

        conn = self._get_connection()

        query = f"SELECT ticker, date, price FROM '{self.prices_file}' WHERE ticker IN ({','.join(['?'] * len(tickers))})"
        params = list(tickers)

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
            
        df = conn.execute(query, params).df()
        
        if df.empty:
            return pd.DataFrame()

        # Pivot
        df['date'] = pd.to_datetime(df['date'])
        pivot_df = df.pivot(index='date', columns='ticker', values='price')
        return pivot_df

    def get_all_tickers(self) -> List[str]:
        if not os.path.exists(self.assets_file):
            return []

        conn = self._get_connection()
        df = conn.execute(f"SELECT ticker FROM '{self.assets_file}'").df()
        return df['ticker'].tolist()

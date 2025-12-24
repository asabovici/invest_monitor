import sqlite3
import pandas as pd
from typing import List, Optional
from src.models import Asset, AssetType, Constituent

class Database:
    def __init__(self, db_path: str = "data/invest_monitor.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Assets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    ticker TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    sector TEXT
                )
            """)
            # Constituents table (for ETF/Fund look-through)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS constituents (
                    parent_ticker TEXT,
                    constituent_ticker TEXT,
                    weight REAL,
                    FOREIGN KEY(parent_ticker) REFERENCES assets(ticker)
                )
            """)
            # Prices table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prices (
                    ticker TEXT,
                    date TEXT,
                    price REAL,
                    PRIMARY KEY (ticker, date),
                    FOREIGN KEY(ticker) REFERENCES assets(ticker)
                )
            """)
            conn.commit()

    def add_asset(self, asset: Asset):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO assets (ticker, name, asset_type, currency, sector)
                VALUES (?, ?, ?, ?, ?)
            """, (asset.ticker, asset.name, asset.asset_type.value, asset.currency, asset.sector))
            
            # Clear old constituents if any
            cursor.execute("DELETE FROM constituents WHERE parent_ticker = ?", (asset.ticker,))
            
            for c in asset.constituents:
                cursor.execute("""
                    INSERT INTO constituents (parent_ticker, constituent_ticker, weight)
                    VALUES (?, ?, ?)
                """, (asset.ticker, c.ticker, c.weight))
            conn.commit()

    def save_prices(self, ticker: str, df: pd.DataFrame):
        """df should have 'Date' index and 'Close' column"""
        with sqlite3.connect(self.db_path) as conn:
            data = [(ticker, date.strftime('%Y-%m-%d'), price) 
                    for date, price in df['Close'].items()]
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO prices (ticker, date, price)
                VALUES (?, ?, ?)
            """, data)
            conn.commit()

    def get_historical_prices(self, tickers: List[str], start_date: str = None) -> pd.DataFrame:
        query = "SELECT ticker, date, price FROM prices WHERE ticker IN ({})".format(
            ','.join(['?'] * len(tickers))
        )
        params = list(tickers)
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
            
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        # Pivot to have dates as index and tickers as columns
        df['date'] = pd.to_datetime(df['date'])
        pivot_df = df.pivot(index='date', columns='ticker', values='price')
        return pivot_df

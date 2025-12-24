import yfinance as yf
import pandas as pd
from src.database import Database
from typing import List

class Collector:
    def __init__(self, db: Database):
        self.db = db

    def collect_prices(self, tickers: List[str], period: str = "1y"):
        """Fetches historical prices for the given tickers and saves them to the database."""
        for ticker in tickers:
            print(f"Fetching prices for {ticker}...")
            try:
                # yfinance returns a DataFrame with 'Close' column
                data = yf.download(ticker, period=period, progress=False)
                if not data.empty:
                    self.db.save_prices(ticker, data)
                else:
                    print(f"No data found for {ticker}")
            except Exception as e:
                print(f"Error fetching data for {ticker}: {e}")

    def update_all_assets(self, period: str = "1mo"):
        """Updates prices for all assets currently in the database."""
        tickers = self.db.get_all_tickers()
        
        if tickers:
            self.collect_prices(tickers, period=period)

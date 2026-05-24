import yfinance as yf
import pandas as pd
from src.database import Database
from src.scenarios import SECTOR_ETF_TICKERS
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

    def fetch_fund_profile(self, fund_ticker: str) -> dict:
        """Fetch asset_classes + sector_weightings from yfinance FundsData.

        Returns {'asset_classes': dict, 'sector_weightings': dict}.
        Raises ValueError if neither breakdown is available.
        """
        fd = yf.Ticker(fund_ticker).funds_data
        asset_classes = dict(fd.asset_classes or {})
        sectors = dict(fd.sector_weightings or {})
        if not asset_classes and not sectors:
            raise ValueError(f"No fund profile data available for {fund_ticker}")
        return {"asset_classes": asset_classes, "sector_weightings": sectors}

    @staticmethod
    def fetch_sector_betas(years: float = 20) -> pd.DataFrame:
        """Fetch SPDR sector ETF prices and compute pairwise OLS sector betas.

        beta(A, B) = Cov(A, B) / Var(B) — "if sector B moves by 1%, sector A
        is expected to move by beta(A, B)%".

        `years` selects the lookback window via explicit start/end dates so we
        aren't limited to yfinance's preset `period` values (1y / 2y / 5y / 10y
        / max). Sector ETFs with shorter history (XLC since 2018, XLRE since
        2015) simply contribute what they have — pairwise covariances are
        computed on the overlap, so the matrix stays consistent.

        Returns a long-format DataFrame: sector_a, sector_b, beta.
        """
        tickers = list(SECTOR_ETF_TICKERS.values())
        end = pd.Timestamp.today().normalize()
        start = end - pd.DateOffset(years=int(years))
        data = yf.download(
            tickers, start=start, end=end, progress=False, auto_adjust=True,
        )
        if isinstance(data.columns, pd.MultiIndex):
            # When fetching >1 ticker, columns are (field, ticker); pick Close.
            close = data["Close"] if "Close" in data.columns.get_level_values(0) else data.iloc[:, :len(tickers)]
        else:
            close = data

        reverse = {v: k for k, v in SECTOR_ETF_TICKERS.items()}
        close = close.rename(columns=reverse)
        # Drop any sector ETFs that returned nothing (e.g. delisted/no history).
        close = close.dropna(axis=1, how="all")
        if close.empty or close.shape[1] < 2:
            raise ValueError("Not enough sector ETF data to compute betas.")

        rets = close.pct_change()
        rows = []
        for a in rets.columns:
            for b in rets.columns:
                if a == b:
                    beta = 1.0
                else:
                    # Use only dates where both sectors have a valid return so
                    # short-history ETFs (XLC, XLRE) still get an honest beta
                    # on their available window.
                    pair = rets[[a, b]].dropna()
                    if len(pair) < 2:
                        beta = 0.0
                    else:
                        var_b = float(pair[b].var())
                        beta = float(pair[a].cov(pair[b]) / var_b) if var_b > 0 else 0.0
                rows.append({"sector_a": a, "sector_b": b, "beta": beta})
        return pd.DataFrame(rows)

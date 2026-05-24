"""Demo-mode seed data: a sample dataset that lives in a separate data_dir
so live portfolios stay hidden when showing off the app.
"""
import os
import shutil
from typing import List, Tuple

import numpy as np
import pandas as pd

from src.database import Database
from src.models import Asset, AssetType, Portfolio, Position

DEMO_DATA_DIR = "data_demo"

# Each row: (ticker, name, asset_type, sector, qty, cost_basis,
#            income_rate, payment_frequency).
# Units of income_rate depend on asset_type:
#   • Stock/ETF/Fund → $ per share PER PAYMENT (annual = rate × payment_frequency)
#   • Bond/CD/Cash   → annual %
_AssetRow = Tuple[str, str, str, str | None, float, float, float, int]

DEMO_PORTFOLIOS: dict[str, List[_AssetRow]] = {
    "Demo Brokerage": [
        ("ACME", "Acme Holdings",          "Stock", "Technology",          50, 230.00, 0.46,  4),
        ("BDRK", "Bedrock Industrial",     "Stock", "Industrials",         30, 165.00, 0.62,  4),
        ("CRST", "Crestpoint Healthcare",  "Stock", "Healthcare",          20, 388.00, 0.49,  4),
        ("DMND", "Diamond S&P Index ETF",  "ETF",   None,                 100, 510.00, 2.04,  4),
        ("EMRD", "Emerald Aggregate Bond", "ETF",   None,                 200,  73.00, 0.26, 12),
    ],
    "Demo Retirement": [
        ("FRTS", "Fortis Total Market",    "ETF",   None,                 150, 300.00, 1.09,  4),
        ("GRNT", "Granite Bond Fund",      "Fund",  None,                 400,  11.50, 0.11,  4),
        ("HRBR", "Harbor Treasury Bond",   "Bond",  None,                 100,  95.50, 4.25,  2),
    ],
    "Demo Cash & CDs": [
        ("USD_DEMO", "Demo USD",           "Cash",  None,               25000,   1.00, 4.50,  1),
        ("CD_18M",   "18-Month CD",        "CD",    None,               50000,   1.00, 4.85, 12),
        ("CD_5Y",    "5-Year CD",          "CD",    None,               30000,   1.00, 4.50, 12),
    ],
}


def is_seeded(db: Database) -> bool:
    """True if the demo dir already has portfolios in it."""
    return len(db.list_portfolios()) > 0


def reset(data_dir: str = DEMO_DATA_DIR) -> None:
    """Delete the demo data directory and start fresh on the next call."""
    if os.path.isdir(data_dir):
        shutil.rmtree(data_dir)


def seed(data_dir: str = DEMO_DATA_DIR, with_prices: bool = True) -> Database:
    """Populate the demo data directory with sample portfolios.

    Idempotent: if the directory already has portfolios, returns the existing
    Database without overwriting. Call `reset()` first to force a re-seed.
    """
    db = Database(data_dir)
    if is_seeded(db):
        return db

    # ── Assets ────────────────────────────────────────────────────────────────
    for rows in DEMO_PORTFOLIOS.values():
        for ticker, name, atype, sector, _qty, _cb, income, freq in rows:
            db.add_asset(Asset(
                ticker=ticker,
                name=name,
                asset_type=AssetType(atype),
                currency="USD",
                sector=sector,
                income_rate=float(income),
                payment_frequency=int(freq),
            ))

    # ── Portfolios + positions ────────────────────────────────────────────────
    for pname, rows in DEMO_PORTFOLIOS.items():
        positions = []
        for ticker, name, atype, sector, qty, cb, income, freq in rows:
            asset = Asset(
                ticker=ticker, name=name,
                asset_type=AssetType(atype),
                currency="USD", sector=sector,
                income_rate=float(income), payment_frequency=int(freq),
            )
            positions.append(Position(asset=asset, quantity=qty, cost_basis=cb))
        db.save_portfolio(Portfolio(name=pname, positions=positions))

    # ── Synthetic prices for equity-like tickers ──────────────────────────────
    if with_prices:
        rng = np.random.default_rng(seed=20260511)
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=504, freq="B")
        for rows in DEMO_PORTFOLIOS.values():
            for ticker, _name, atype, _sector, _qty, cb, _income, _freq in rows:
                if atype in ("Cash", "CD"):
                    continue  # constant-1.0 series is auto-generated
                # Per-asset-type drift/vol for realism
                mu, sigma = {
                    "Stock": (0.00040, 0.014),
                    "ETF":   (0.00030, 0.010),
                    "Fund":  (0.00025, 0.008),
                    "Bond":  (0.00010, 0.004),
                }.get(atype, (0.0002, 0.010))
                shocks = rng.normal(mu, sigma, len(dates))
                # Anchor end-of-series to ~ cost_basis × (1 + small drift)
                path = np.cumprod(1 + shocks)
                end_target = cb * float(rng.uniform(0.92, 1.18))
                scale = end_target / path[-1]
                prices = pd.DataFrame(
                    {"Close": path * scale},
                    index=dates,
                )
                db.save_prices(ticker, prices)

    # ── Fake yfinance fund-profile snapshot for the equity ETF ────────────────
    today = pd.Timestamp.today().date().isoformat()
    db.save_fund_profile(
        "DMND", today,
        asset_classes={
            "stockPosition": 0.99, "bondPosition": 0.0, "cashPosition": 0.01,
            "preferredPosition": 0.0, "convertiblePosition": 0.0, "otherPosition": 0.0,
        },
        sector_weightings={
            "technology": 0.30, "healthcare": 0.13, "financial_services": 0.13,
            "consumer_cyclical": 0.11, "consumer_defensive": 0.06,
            "communication_services": 0.10, "industrials": 0.08,
            "energy": 0.04, "utilities": 0.02, "basic_materials": 0.02,
            "realestate": 0.01,
        },
    )
    db.save_fund_profile(
        "EMRD", today,
        asset_classes={
            "stockPosition": 0.0, "bondPosition": 0.99, "cashPosition": 0.01,
            "preferredPosition": 0.0, "convertiblePosition": 0.0, "otherPosition": 0.0,
        },
        sector_weightings={},
    )

    return db

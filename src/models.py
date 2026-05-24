from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

class AssetType(Enum):
    STOCK = "Stock"
    BOND = "Bond"
    ETF = "ETF"
    FUND = "Fund"
    CASH = "Cash"
    CD = "CD"
    CRYPTO = "Crypto"

@dataclass
class Constituent:
    ticker: str
    weight: float  # Percentage (0.0 to 1.0)
    name: Optional[str] = None

@dataclass
class Asset:
    ticker: str
    asset_type: AssetType
    name: str
    currency: str = "USD"
    sector: Optional[str] = None
    # Income — units depend on asset_type:
    #   • Stock / ETF / Fund : dollars per share PER PAYMENT
    #                          (annual = quantity × income_rate × payment_frequency)
    #                          e.g. BLK pays $5.72 quarterly → income_rate=5.72, payment_frequency=4
    #   • Bond / CD / Cash   : annual rate as a percent
    #                          (annual = base_value × income_rate / 100)
    #                          e.g. 4.5 for a 4.5% coupon / yield
    #   • Crypto / unknown   : annual rate as a percent (default 0)
    income_rate: float = 0.0
    # Payments per year (1 annual, 2 semi-annual, 4 quarterly, 12 monthly).
    # Only meaningful for Bond and CD; defaults to 1 elsewhere.
    payment_frequency: int = 1
    constituents: List[Constituent] = field(default_factory=list)

    def is_composite(self) -> bool:
        return len(self.constituents) > 0

@dataclass
class Position:
    asset: Asset
    quantity: float
    cost_basis: float

@dataclass
class Portfolio:
    name: str
    positions: List[Position] = field(default_factory=list)

    def total_cost(self) -> float:
        return sum(p.quantity * p.cost_basis for p in self.positions)

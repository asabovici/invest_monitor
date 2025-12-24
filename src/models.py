from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

class AssetType(Enum):
    STOCK = "Stock"
    BOND = "Bond"
    ETF = "ETF"
    FUND = "Fund"
    CASH = "Cash"
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
        return sum(p.quantity * p.cost_basis for p in p.positions)

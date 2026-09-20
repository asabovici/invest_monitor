"""HTTP route for portfolio-wide income projection."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.api.deps import data_dir_dep
from src.services import income as income_service
from src.services.schemas.income import IncomeReport

router = APIRouter(prefix="/income", tags=["income"])


@router.get("", response_model=IncomeReport)
def get_income(data_dir: Annotated[str, Depends(data_dir_dep)]) -> IncomeReport:
    """Projected annual and monthly income across every account.

    The total is a floor: holdings with no income rate on record contribute
    nothing and are listed separately.
    """
    return income_service.get_income(data_dir)

"""HTTP routes for scenarios (slice 5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import data_dir_dep
from src.api.schemas.scenario import (
    MCScenarioInfo,
    RegimePresetInfo,
    StressScenarioInfo,
    StressTestRequest,
    StressTestResult,
)
from src.services import scenarios as scenarios_service

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("/stress", response_model=list[StressScenarioInfo])
def list_stress_scenarios() -> list[StressScenarioInfo]:
    """All named sector-stress presets with their shock dicts."""
    return scenarios_service.list_stress_scenarios()


@router.get("/mc", response_model=list[MCScenarioInfo])
def list_mc_scenarios() -> list[MCScenarioInfo]:
    """All multi-phase Monte Carlo scenarios."""
    return scenarios_service.list_mc_scenarios()


@router.get("/regimes", response_model=list[RegimePresetInfo])
def list_wealth_regimes() -> list[RegimePresetInfo]:
    """Historical regime presets used by wealth MC projections."""
    return scenarios_service.list_wealth_regimes()


@router.post("/stress/{portfolio_name}", response_model=StressTestResult)
def run_sector_stress(
    portfolio_name: str,
    body: StressTestRequest,
    data_dir: Annotated[str, Depends(data_dir_dep)],
) -> StressTestResult:
    """Apply sector + non-equity shocks to a portfolio and report P/L per position.

    404 if the portfolio doesn't exist; 400 if the scenario_id is unknown or
    no shocks were specified.
    """
    try:
        return scenarios_service.run_sector_stress(
            data_dir,
            portfolio_name,
            scenario_id=body.scenario_id,
            custom_sector_shocks=body.custom_sector_shocks,
            custom_non_equity_shocks=body.custom_non_equity_shocks,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in msg.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg) from exc

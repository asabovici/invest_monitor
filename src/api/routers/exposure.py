"""HTTP route for look-through exposure."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.api.deps import data_dir_dep
from src.services import exposure as exposure_service
from src.services.schemas.exposure import ExposureReport

router = APIRouter(prefix="/exposure", tags=["exposure"])


@router.get("", response_model=ExposureReport)
def get_exposure(data_dir: Annotated[str, Depends(data_dir_dep)]) -> ExposureReport:
    """Asset-class and equity-sector exposure, looked through fund holdings.

    Sector weights are a share of the equity sleeve only — bond and commodity
    funds have no sector breakdown by construction.
    """
    return exposure_service.get_exposure(data_dir)

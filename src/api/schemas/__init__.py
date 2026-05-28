"""Backwards-compat re-export of the canonical schemas.

Schemas live in ``src.services.schemas`` so the service layer can own them
without depending on the API layer. Imports of the form
``from src.api.schemas.portfolio import X`` keep working via the submodule
aliases below — useful for any external code that already references the
old paths.
"""

from src.services import schemas as _services_schemas
from src.services.schemas import benchmark, portfolio, price, report, scenario

# Re-bind the submodules so ``from src.api.schemas.portfolio import X`` resolves.
import sys as _sys
for _name, _mod in (
    ("portfolio", portfolio),
    ("price", price),
    ("report", report),
    ("scenario", scenario),
    ("benchmark", benchmark),
):
    _sys.modules[f"{__name__}.{_name}"] = _mod

__all__ = ["benchmark", "portfolio", "price", "report", "scenario"]

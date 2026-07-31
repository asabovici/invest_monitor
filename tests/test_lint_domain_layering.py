"""Ratchet test: cap direct domain-class references in the UI/CLI layers.

The API refactor moves business logic into ``src/services`` and asks
``src/app.py`` (Streamlit) and ``src/cli.py`` (Click) to go through the
service layer rather than the raw domain classes. A handful of escape
hatches remain — fund-holdings CSV upload, ``Database`` for the
production ``daemon`` command, ``ReportingEngine`` for the ad-hoc
``calculate_returns`` chart panels — and the goal of this test is
**to keep that handful from growing**.

For each watched file we count occurrences of the forbidden class names
(matching whole words via ``re.escape`` + word boundaries) and assert the
count is at or below ``MAX_DIRECT_REFS``. When you migrate a site:

1. Run the test — it'll report the new lower number.
2. Drop the cap in ``MAX_DIRECT_REFS`` accordingly.

Each future cleanup PR ratchets the cap down. New direct references
fail the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

# Domain classes that the service layer wraps. Any whole-word occurrence
# of these names in the watched files counts toward the cap, including
# imports, instantiations, and type annotations.
FORBIDDEN = (
    "Database",
    "ReportingEngine",
    "AttributionEngine",
    "Collector",
    "Ingester",
    "JobRunner",
)

# Cap per watched file — the ratchet. Drop the number when you migrate a
# site. Numbers below were measured after slice 10 (the cleanup pass).
MAX_DIRECT_REFS: dict[str, int] = {
    "src/app.py": 15,
    "src/cli.py": 5,
}

_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(c) for c in FORBIDDEN) + r")\b")


def _count_direct_refs(rel_path: str) -> int:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    return len(_PATTERN.findall(text))


@pytest.mark.parametrize("rel_path, max_refs", sorted(MAX_DIRECT_REFS.items()))
def test_direct_domain_refs_within_cap(rel_path: str, max_refs: int) -> None:
    count = _count_direct_refs(rel_path)
    assert count <= max_refs, (
        f"\n{rel_path} has {count} direct references to one of "
        f"{', '.join(FORBIDDEN)} — cap is {max_refs}.\n"
        f"Either migrate the new site through src.services or — if this is "
        f"intentional — bump MAX_DIRECT_REFS[{rel_path!r}] in this test."
    )


def test_cap_is_not_too_loose() -> None:
    """If the actual count is below the cap, tighten the cap.

    Prevents the ratchet from silently drifting upward over time.
    """
    too_loose: dict[str, tuple[int, int]] = {}
    for rel_path, cap in MAX_DIRECT_REFS.items():
        actual = _count_direct_refs(rel_path)
        if actual < cap:
            too_loose[rel_path] = (actual, cap)
    assert not too_loose, (
        "\nThese caps are looser than the measured count — tighten them:\n  "
        + "\n  ".join(
            f"{p}: actual={a}, cap={c} → set MAX_DIRECT_REFS[{p!r}] = {a}"
            for p, (a, c) in too_loose.items()
        )
    )

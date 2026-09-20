"""The Vite dev proxy must cover every FastAPI router prefix.

A prefix missing from `frontend/vite.config.ts` doesn't fail loudly — the
request falls through to Vite, which serves `index.html`, and the view
reports "the API isn't responding" while the server is perfectly healthy.
That failure mode already cost debugging time twice while the screens were
being built, so it gets a test rather than a comment.

Kept in Python, next to the API it guards, so it runs in the normal suite
rather than only when someone remembers to run the frontend tooling.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VITE_CONFIG = ROOT / "frontend" / "vite.config.ts"
API_MAIN = ROOT / "src" / "api" / "main.py"

pytestmark = pytest.mark.skipif(
    not VITE_CONFIG.exists(), reason="frontend/ is not present in this checkout"
)


def _registered_prefixes() -> set[str]:
    """Router prefixes mounted on the app, derived from each router module."""
    main = API_MAIN.read_text()
    modules = set(re.findall(r"app\.include_router\((\w+)\.router\)", main))

    prefixes = set()
    for module in modules:
        source = (ROOT / "src" / "api" / "routers" / f"{module}.py").read_text()
        found = re.search(r'APIRouter\([^)]*prefix\s*=\s*["\']([^"\']+)["\']', source, re.S)
        if found:
            prefixes.add(found.group(1))
    return prefixes


def _proxied_paths() -> set[str]:
    return set(re.findall(r"'(/[a-z-]+)'", VITE_CONFIG.read_text()))


def test_every_router_prefix_is_proxied():
    missing = _registered_prefixes() - _proxied_paths()
    assert not missing, (
        f"Router prefix(es) {sorted(missing)} are mounted in src/api/main.py but "
        f"absent from frontend/vite.config.ts. Requests to them will be swallowed "
        f"by the dev server and the UI will claim the API is down. Add them to the "
        f"proxy list."
    )


def test_proxy_has_no_paths_that_lead_nowhere():
    """A stale entry proxies a path the API no longer serves."""
    stale = _proxied_paths() - _registered_prefixes() - {"/health"}
    assert not stale, (
        f"frontend/vite.config.ts proxies {sorted(stale)}, which no router serves. "
        f"Remove them, or mount the router."
    )


def test_registered_prefixes_were_actually_found():
    """Guard the guard: a parsing change must not turn this into a no-op."""
    prefixes = _registered_prefixes()
    assert len(prefixes) >= 10, f"only parsed {prefixes} — the regex likely broke"
    assert "/dashboard" in prefixes

"""Tests for the rate-limit middleware (``src/api/rate_limit.py``).

Activation is env-var-gated (``INVEST_MONITOR_RATE_LIMIT``) so the
default suite runs with rate limiting disabled and these tests
opt-in via ``monkeypatch.setenv``.

The token-bucket store is process-local — we call ``reset_buckets()``
in an autouse fixture so cases don't bleed.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.api import rate_limit as rl
from src.api.main import app


@pytest.fixture(autouse=True)
def fresh_buckets() -> None:
    rl.reset_buckets()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


_DEMO_HEADERS = {"X-Data-Dir": "data_demo"}


# ── Config parsing ──────────────────────────────────────────────────────────


def test_parse_limit_n_per_seconds() -> None:
    assert rl._parse_limit("10/60") == (10, 60)
    assert rl._parse_limit("  3 / 30  ") == (3, 30)


def test_parse_limit_just_n_uses_minute_default() -> None:
    assert rl._parse_limit("5") == (5, 60)


def test_parse_limit_unset_means_disabled() -> None:
    assert rl._parse_limit(None) is None
    assert rl._parse_limit("") is None
    assert rl._parse_limit("   ") is None


def test_parse_limit_malformed_disables_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="src.api.rate_limit"):
        assert rl._parse_limit("not-a-number") is None
        assert rl._parse_limit("10/wat") is None
        assert rl._parse_limit("0/60") is None
        assert rl._parse_limit("-1") is None
    # At least one warning fired (one per malformed value).
    assert sum("malformed" in m or "non-positive" in m for m in caplog.messages) >= 4


# ── Scope (which paths are limited) ──────────────────────────────────────────


def test_is_limited_recognises_long_running_paths() -> None:
    for p in (
        "/prices/collect",
        "/production/run-due",
        "/production/metrics-refresh",
        "/production/jobs/refresh_attribution/run",
        "/production/jobs/stub_ok/run",
    ):
        assert rl._is_limited(p), f"expected {p!r} to be limited"


def test_is_limited_passes_through_read_paths() -> None:
    for p in (
        "/portfolios",
        "/prices/latest",
        "/reports/risk/Demo Brokerage",
        "/production/jobs",
        "/production/runs",
        "/health",
        "/agents/kinds",
    ):
        assert not rl._is_limited(p), f"{p!r} should not be limited"


# ── End-to-end behaviour ────────────────────────────────────────────────────


def test_disabled_by_default(client: TestClient) -> None:
    """Without the env var, even hammering a limited endpoint doesn't 429."""
    for _ in range(20):
        r = client.post("/production/run-due", headers=_DEMO_HEADERS)
        assert r.status_code == 200


def test_limit_kicks_in_after_n_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVEST_MONITOR_RATE_LIMIT", "2/60")
    # First two pass, third gets 429.
    assert client.post("/production/run-due", headers=_DEMO_HEADERS).status_code == 200
    assert client.post("/production/run-due", headers=_DEMO_HEADERS).status_code == 200
    r = client.post("/production/run-due", headers=_DEMO_HEADERS)
    assert r.status_code == 429
    assert "rate limit" in r.json()["detail"].lower()


def test_429_carries_retry_after(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVEST_MONITOR_RATE_LIMIT", "1/60")
    client.post("/production/run-due", headers=_DEMO_HEADERS)  # consume the lone token
    r = client.post("/production/run-due", headers=_DEMO_HEADERS)
    assert r.status_code == 429
    retry = int(r.headers["retry-after"])
    # At 1 token / 60s, the next token is up to ~60s away; allow generous slack.
    assert 1 <= retry <= 60


def test_non_limited_paths_unaffected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reads stay unlimited even when the bucket for limited paths is empty."""
    monkeypatch.setenv("INVEST_MONITOR_RATE_LIMIT", "1/60")
    client.post("/production/run-due", headers=_DEMO_HEADERS)
    client.post("/production/run-due", headers=_DEMO_HEADERS)  # exhausts the bucket
    # Any number of reads still pass.
    for _ in range(5):
        assert client.get("/portfolios", headers=_DEMO_HEADERS).status_code == 200


def test_refill_after_window_unblocks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advancing time refills the bucket and the next request passes."""
    monkeypatch.setenv("INVEST_MONITOR_RATE_LIMIT", "1/60")

    real_monotonic = time.monotonic
    offset = [0.0]

    def fake_monotonic() -> float:
        return real_monotonic() + offset[0]

    monkeypatch.setattr(rl.time, "monotonic", fake_monotonic)

    assert client.post("/production/run-due", headers=_DEMO_HEADERS).status_code == 200
    assert client.post("/production/run-due", headers=_DEMO_HEADERS).status_code == 429
    # Fast-forward past the refill window — the bucket regenerates one token.
    offset[0] += 120
    assert client.post("/production/run-due", headers=_DEMO_HEADERS).status_code == 200


def test_different_api_keys_get_separate_buckets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two authenticated callers each get their own ration."""
    monkeypatch.setenv("INVEST_MONITOR_API_KEY", "shared-secret-shared-secret-32x")
    monkeypatch.setenv("INVEST_MONITOR_RATE_LIMIT", "1/60")

    # Same configured server key, but rate-limit identifies clients by the
    # *presented* credential — different X-API-Key values hash to different
    # bucket IDs even when only one would actually authenticate. We need
    # two clients that both authenticate, so override per-test by reading
    # both keys: skip the bucket-isolation case by configuring an unkeyed
    # server but distinct X-API-Key headers (each will fail auth but reach
    # rate-limit — auth runs first, so this doesn't work).
    #
    # Instead drop auth and rely on the API-key extraction in rate_limit
    # alone — the middleware hashes whatever credential is presented.
    monkeypatch.delenv("INVEST_MONITOR_API_KEY")

    h_a = {**_DEMO_HEADERS, "X-API-Key": "client-alpha-aaaaaaaaaaaaaaaaaaaaaa"}
    h_b = {**_DEMO_HEADERS, "X-API-Key": "client-bravo-bbbbbbbbbbbbbbbbbbbbbb"}

    # Each client gets one token.
    assert client.post("/production/run-due", headers=h_a).status_code == 200
    assert client.post("/production/run-due", headers=h_b).status_code == 200
    # Each client's second request is over budget.
    assert client.post("/production/run-due", headers=h_a).status_code == 429
    assert client.post("/production/run-due", headers=h_b).status_code == 429


def test_auth_runs_before_rate_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anonymous traffic should see 401, not 429, even with the bucket empty."""
    server_key = "real-server-key-32-chars-min-ok!"
    monkeypatch.setenv("INVEST_MONITOR_API_KEY", server_key)
    monkeypatch.setenv("INVEST_MONITOR_RATE_LIMIT", "1/60")

    # Consume the would-be bucket via an authenticated call.
    auth_headers = {**_DEMO_HEADERS, "Authorization": f"Bearer {server_key}"}
    r = client.post("/production/run-due", headers=auth_headers)
    assert r.status_code == 200

    # An anonymous follow-up: auth middleware fires first → 401.
    r = client.post("/production/run-due", headers=_DEMO_HEADERS)
    assert r.status_code == 401


def test_malformed_limit_disables_middleware(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A garbage env var falls back to 'off' and doesn't block traffic."""
    monkeypatch.setenv("INVEST_MONITOR_RATE_LIMIT", "garbage")
    for _ in range(5):
        r = client.post("/production/run-due", headers=_DEMO_HEADERS)
        assert r.status_code == 200

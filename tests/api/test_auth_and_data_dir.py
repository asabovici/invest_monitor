"""Tests for the auth middleware + X-Data-Dir allowlist.

Both protections are env-var-gated:

- ``INVEST_MONITOR_API_KEY`` enables ``APIKeyAuthMiddleware``.
- ``INVEST_MONITOR_ALLOWED_DATA_DIRS`` enables the allowlist check in
  ``data_dir_dep``.

Either env var unset → that protection is a no-op. Tests use
``monkeypatch.setenv`` so the rest of the suite (which runs without
either env var) keeps behaving exactly as before.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


_KEY = "test-key-abc-123"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ── Auth disabled (default) ──────────────────────────────────────────────────


def test_no_key_configured_means_no_auth_required(client: TestClient) -> None:
    """Without the env var, requests pass through unchanged."""
    r = client.get("/portfolios", headers={"X-Data-Dir": "data_demo"})
    assert r.status_code == 200


# ── Auth enabled ─────────────────────────────────────────────────────────────


@pytest.fixture
def auth_enabled(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("INVEST_MONITOR_API_KEY", _KEY)
    return _KEY


def test_missing_credential_returns_401(client: TestClient, auth_enabled: str) -> None:
    r = client.get("/portfolios", headers={"X-Data-Dir": "data_demo"})
    assert r.status_code == 401
    assert "Authentication" in r.json()["detail"]
    assert r.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_wrong_bearer_returns_401(client: TestClient, auth_enabled: str) -> None:
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "data_demo", "Authorization": "Bearer wrong-key"},
    )
    assert r.status_code == 401


def test_correct_bearer_passes(client: TestClient, auth_enabled: str) -> None:
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "data_demo", "Authorization": f"Bearer {auth_enabled}"},
    )
    assert r.status_code == 200


def test_correct_x_api_key_passes(client: TestClient, auth_enabled: str) -> None:
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "data_demo", "X-API-Key": auth_enabled},
    )
    assert r.status_code == 200


def test_non_bearer_authorization_rejected(client: TestClient, auth_enabled: str) -> None:
    """Basic auth or other schemes don't pass — only Bearer + X-API-Key."""
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "data_demo", "Authorization": f"Basic {auth_enabled}"},
    )
    assert r.status_code == 401


def test_lowercase_bearer_accepted(client: TestClient, auth_enabled: str) -> None:
    """RFC 6750 says the scheme is case-insensitive."""
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "data_demo", "Authorization": f"bearer {auth_enabled}"},
    )
    assert r.status_code == 200


def test_empty_bearer_token_returns_401(client: TestClient, auth_enabled: str) -> None:
    """``Authorization: Bearer `` with nothing after should not match."""
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "data_demo", "Authorization": "Bearer "},
    )
    assert r.status_code == 401


def test_bearer_takes_precedence_over_x_api_key(
    client: TestClient, auth_enabled: str
) -> None:
    """When Authorization is Bearer, X-API-Key is ignored — so a wrong Bearer
    token blocks the request even if X-API-Key is correct."""
    r = client.get(
        "/portfolios",
        headers={
            "X-Data-Dir": "data_demo",
            "Authorization": "Bearer wrong-token",
            "X-API-Key": auth_enabled,
        },
    )
    assert r.status_code == 401


def test_non_bearer_authorization_falls_through_to_x_api_key(
    client: TestClient, auth_enabled: str
) -> None:
    """If Authorization uses an unknown scheme, X-API-Key is consulted."""
    r = client.get(
        "/portfolios",
        headers={
            "X-Data-Dir": "data_demo",
            "Authorization": "Basic dXNlcjpwYXNz",  # arbitrary base64
            "X-API-Key": auth_enabled,
        },
    )
    assert r.status_code == 200


def test_health_exempt_from_auth(client: TestClient, auth_enabled: str) -> None:
    r = client.get("/health")
    assert r.status_code == 200


def test_openapi_exempt_from_auth(client: TestClient, auth_enabled: str) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200


def test_docs_exempt_from_auth(client: TestClient, auth_enabled: str) -> None:
    # Swagger UI is rendered HTML; just check the route is reachable.
    r = client.get("/docs")
    assert r.status_code == 200


def test_redoc_exempt_from_auth(client: TestClient, auth_enabled: str) -> None:
    r = client.get("/redoc")
    assert r.status_code == 200


def test_short_key_emits_advisory_warning(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A short key should still authenticate but emit a one-shot warning."""
    import logging
    # Use a value that hasn't appeared in earlier tests so the lru_cache
    # warning slot is fresh.
    short_key = "short-key-001"  # 13 chars, well under the 32-byte threshold
    monkeypatch.setenv("INVEST_MONITOR_API_KEY", short_key)
    with caplog.at_level(logging.WARNING, logger="src.api.auth"):
        r = client.get(
            "/portfolios",
            headers={"X-Data-Dir": "data_demo", "Authorization": f"Bearer {short_key}"},
        )
    assert r.status_code == 200
    assert any("32 recommended" in m for m in caplog.messages)


def test_auth_runs_before_body_size_limit(
    client: TestClient, auth_enabled: str
) -> None:
    """A huge unauthenticated body should 401, not 413 — auth wraps body-size."""
    import json
    big_payload = json.dumps({"name": "x", "csv_text": "a" * (20 * 1024 * 1024)})
    r = client.post(
        "/portfolios/load-csv",
        data=big_payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(big_payload)),
        },
    )
    # Hit by the auth middleware first; the body never gets read.
    assert r.status_code == 401


# ── Path-traversal allowlist ────────────────────────────────────────────────


@pytest.fixture
def allowlist_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVEST_MONITOR_ALLOWED_DATA_DIRS", "data,data_demo")


def test_no_allowlist_means_any_data_dir_accepted(
    client: TestClient, tmp_path
) -> None:
    """Without the env var, arbitrary X-Data-Dir values pass (legacy behaviour)."""
    headers = {"X-Data-Dir": str(tmp_path)}
    r = client.post("/portfolios", json={"name": "P1"}, headers=headers)
    assert r.status_code == 201


def test_allowed_data_dir_passes(
    client: TestClient, allowlist_enabled: None
) -> None:
    r = client.get("/portfolios", headers={"X-Data-Dir": "data_demo"})
    assert r.status_code == 200


def test_blocked_data_dir_returns_400(
    client: TestClient, allowlist_enabled: None
) -> None:
    r = client.get("/portfolios", headers={"X-Data-Dir": "/etc"})
    assert r.status_code == 400
    assert "allowlist" in r.json()["detail"].lower()


def test_path_traversal_attempt_blocked(
    client: TestClient, allowlist_enabled: None
) -> None:
    for evil in ("../etc", "../../etc/passwd", "data/../../../etc"):
        r = client.get("/portfolios", headers={"X-Data-Dir": evil})
        assert r.status_code == 400, f"expected 400 for {evil!r}, got {r.status_code}"


def test_env_default_must_also_be_in_allowlist(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A misconfigured ``INVEST_MONITOR_DATA_DIR`` is rejected too."""
    monkeypatch.setenv("INVEST_MONITOR_ALLOWED_DATA_DIRS", "data_demo")
    monkeypatch.setenv("INVEST_MONITOR_DATA_DIR", "/etc")
    # No X-Data-Dir header → falls through to env-var default → rejected.
    r = client.get("/portfolios")
    assert r.status_code == 400


def test_allowlist_with_whitespace_entries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whitespace around comma-separated entries is tolerated."""
    monkeypatch.setenv("INVEST_MONITOR_ALLOWED_DATA_DIRS", " data , data_demo ")
    r = client.get("/portfolios", headers={"X-Data-Dir": "data_demo"})
    assert r.status_code == 200


# ── Combined ─────────────────────────────────────────────────────────────────


def test_auth_and_allowlist_together(
    client: TestClient, auth_enabled: str, allowlist_enabled: None
) -> None:
    """Both gates active. Allowed dir + correct key = 200."""
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "data_demo", "X-API-Key": auth_enabled},
    )
    assert r.status_code == 200


def test_auth_passes_but_allowlist_blocks(
    client: TestClient, auth_enabled: str, allowlist_enabled: None
) -> None:
    """Correct key but disallowed data dir = 400 from the dep."""
    r = client.get(
        "/portfolios",
        headers={"X-Data-Dir": "/etc", "X-API-Key": auth_enabled},
    )
    assert r.status_code == 400

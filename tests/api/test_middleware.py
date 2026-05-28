"""Tests for the body-size-limit middleware."""

import json

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.middleware import DEFAULT_MAX_BODY_BYTES


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_small_request_passes_through(client: TestClient, tmp_path) -> None:
    """A normal-sized request is unaffected by the body-size cap."""
    headers = {"X-Data-Dir": str(tmp_path)}
    r = client.post("/portfolios", json={"name": "OK"}, headers=headers)
    assert r.status_code == 201


def test_content_length_above_cap_returns_413(client: TestClient) -> None:
    """An advertised Content-Length above the cap is rejected without reading the body."""
    big_payload = json.dumps({
        "name": "x",
        "csv_text": "a" * (DEFAULT_MAX_BODY_BYTES + 1024),
    })
    r = client.post(
        "/portfolios/load-csv",
        data=big_payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(big_payload)),
        },
    )
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]

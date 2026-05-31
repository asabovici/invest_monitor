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


def test_chunked_upload_above_cap_returns_413(client: TestClient) -> None:
    """Chunked / streaming uploads (no Content-Length) also hit the cap.

    Exercises the receive-wrapper branch: when httpx sends ``content=`` as
    a generator it uses ``Transfer-Encoding: chunked`` and omits the
    Content-Length header, so the early short-circuit can't fire.
    The middleware then has to tally bytes per chunk and short-circuit
    once the cap is crossed.
    """
    chunk = b"a" * (1024 * 1024)  # 1 MB per chunk
    total_chunks = (DEFAULT_MAX_BODY_BYTES // len(chunk)) + 2  # comfortably over the cap

    def body_iter():
        # Wrap the giant payload in a JSON skeleton so the app, if it
        # ever got to read it, would see a syntactically plausible body.
        yield b'{"name":"x","csv_text":"'
        for _ in range(total_chunks):
            yield chunk
        yield b'"}'

    r = client.post(
        "/portfolios/load-csv",
        content=body_iter(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]


def test_chunked_upload_within_cap_passes(client: TestClient, tmp_path) -> None:
    """A modest streaming upload still reaches the handler."""
    headers = {"X-Data-Dir": str(tmp_path), "Content-Type": "application/json"}
    payload = json.dumps({"name": "Streamed"}).encode()
    # Split the payload across two chunks so we exercise the chunked path
    # without breaching the cap.
    half = len(payload) // 2

    def body_iter():
        yield payload[:half]
        yield payload[half:]

    r = client.post("/portfolios", content=body_iter(), headers=headers)
    assert r.status_code == 201

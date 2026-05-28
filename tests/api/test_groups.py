"""Tests for /groups HTTP routes via FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def headers(tmp_path) -> dict[str, str]:
    h = {"X-Data-Dir": str(tmp_path)}
    return h


@pytest.fixture
def seeded(client: TestClient, headers) -> dict[str, str]:
    """Seed two portfolios for membership tests."""
    client.post("/portfolios", json={"name": "P1"}, headers=headers)
    client.post("/portfolios", json={"name": "P2"}, headers=headers)
    return headers


def test_list_empty(client: TestClient, headers) -> None:
    r = client.get("/groups", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_create_then_get(client: TestClient, headers) -> None:
    r = client.post("/groups", json={"name": "Tax-Free", "description": "d"}, headers=headers)
    assert r.status_code == 201
    r2 = client.get("/groups/Tax-Free", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["description"] == "d"


def test_create_idempotent_updates_description(client: TestClient, headers) -> None:
    client.post("/groups", json={"name": "G", "description": "v1"}, headers=headers)
    r = client.post("/groups", json={"name": "G", "description": "v2"}, headers=headers)
    assert r.json()["description"] == "v2"


def test_get_unknown_group_404(client: TestClient, headers) -> None:
    assert client.get("/groups/no-such", headers=headers).status_code == 404


def test_add_remove_member_flow(client: TestClient, seeded) -> None:
    client.post("/groups", json={"name": "G"}, headers=seeded)
    r = client.post("/groups/G/members/P1", headers=seeded)
    assert r.status_code == 200
    assert r.json()["members"] == ["P1"]
    r = client.delete("/groups/G/members/P1", headers=seeded)
    assert r.status_code == 200
    assert r.json()["members"] == []


def test_set_members_replaces_atomically(client: TestClient, seeded) -> None:
    client.post("/groups", json={"name": "G"}, headers=seeded)
    client.post("/groups/G/members/P1", headers=seeded)
    r = client.put("/groups/G/members", json={"portfolios": ["P2"]}, headers=seeded)
    assert r.status_code == 200
    assert r.json()["members"] == ["P2"]


def test_set_members_unknown_portfolio_400(client: TestClient, seeded) -> None:
    client.post("/groups", json={"name": "G"}, headers=seeded)
    r = client.put(
        "/groups/G/members", json={"portfolios": ["P1", "Ghost"]}, headers=seeded,
    )
    assert r.status_code == 400


def test_add_member_to_unknown_group_404(client: TestClient, seeded) -> None:
    r = client.post("/groups/Imaginary/members/P1", headers=seeded)
    assert r.status_code == 404


def test_delete_group_204(client: TestClient, headers) -> None:
    client.post("/groups", json={"name": "Goner"}, headers=headers)
    assert client.delete("/groups/Goner", headers=headers).status_code == 204


def test_delete_unknown_group_404(client: TestClient, headers) -> None:
    assert client.delete("/groups/Imaginary", headers=headers).status_code == 404


def test_portfolio_groups_round_trip(client: TestClient, seeded) -> None:
    client.post("/groups", json={"name": "A"}, headers=seeded)
    client.post("/groups", json={"name": "B"}, headers=seeded)
    r = client.put(
        "/portfolios/P1/groups", json={"group_names": ["A", "B"]}, headers=seeded,
    )
    assert r.status_code == 200
    assert r.json() == ["A", "B"]
    r2 = client.get("/portfolios/P1/groups", headers=seeded)
    assert r2.status_code == 200
    assert r2.json() == ["A", "B"]


def test_portfolio_groups_unknown_group_400(client: TestClient, seeded) -> None:
    r = client.put(
        "/portfolios/P1/groups", json={"group_names": ["Imaginary"]}, headers=seeded,
    )
    assert r.status_code == 400


def test_portfolio_groups_unknown_portfolio_404(client: TestClient, headers) -> None:
    r = client.get("/portfolios/Ghost/groups", headers=headers)
    assert r.status_code == 404

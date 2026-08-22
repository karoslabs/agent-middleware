from typing import Any

from fastapi.testclient import TestClient


def test_create_agent_returns_slug_as_id(client: TestClient) -> None:
    response = client.post("/agents", json={"slug": "writer", "name": "Writer"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == "writer"
    assert body["slug"] == "writer"
    assert body["status"] == "active"
    assert body["deleted_at"] is None


def test_duplicate_slug_is_rejected(client: TestClient) -> None:
    client.post("/agents", json={"slug": "writer", "name": "Writer"})

    duplicate = client.post("/agents", json={"slug": "writer", "name": "Other"})

    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_invalid_slug_is_rejected(client: TestClient) -> None:
    response = client.post("/agents", json={"slug": "Not A Slug", "name": "Writer"})

    assert response.status_code == 422


def test_get_unknown_agent_returns_404(client: TestClient) -> None:
    assert client.get("/agents/nope").status_code == 404


def test_update_agent_patches_only_given_fields(
    client: TestClient, agent: dict[str, Any]
) -> None:
    response = client.patch(
        f"/agents/{agent['id']}", json={"model_params": {"temperature": 0.9}}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_params"] == {"temperature": 0.9}
    assert body["name"] == agent["name"]
    assert body["model"] == agent["model"]


def test_disable_and_reenable_agent(client: TestClient, agent: dict[str, Any]) -> None:
    disabled = client.patch(f"/agents/{agent['id']}/status", json={"status": "disabled"})
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    enabled = client.patch(f"/agents/{agent['id']}/status", json={"status": "active"})
    assert enabled.json()["status"] == "active"


def test_logical_delete_hides_agent_but_keeps_document(
    client: TestClient, agent: dict[str, Any]
) -> None:
    deleted = client.delete(f"/agents/{agent['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert deleted.json()["status"] == "disabled"

    assert client.get(f"/agents/{agent['id']}").status_code == 404
    assert client.get(f"/agents/{agent['id']}?include_deleted=true").status_code == 200

    restored = client.post(f"/agents/{agent['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


def test_list_agents_filters_and_excludes_deleted(client: TestClient) -> None:
    client.post("/agents", json={"slug": "a-writer", "name": "Alpha", "tags": ["content"]})
    client.post("/agents", json={"slug": "b-builder", "name": "Beta", "agent_type": "pages"})
    client.delete("/agents/b-builder")

    listed = client.get("/agents").json()
    assert [item["id"] for item in listed["items"]] == ["a-writer"]
    assert listed["total"] == 1
    assert listed["has_more"] is False

    with_deleted = client.get("/agents?include_deleted=true").json()
    assert with_deleted["total"] == 2

    by_tag = client.get("/agents?tag=content").json()
    assert [item["id"] for item in by_tag["items"]] == ["a-writer"]

    by_query = client.get("/agents?q=beta&include_deleted=true").json()
    assert [item["id"] for item in by_query["items"]] == ["b-builder"]

    by_type = client.get("/agents?agent_type=pages&include_deleted=true").json()
    assert [item["id"] for item in by_type["items"]] == ["b-builder"]


def test_list_agents_paginates(client: TestClient) -> None:
    for index in range(3):
        client.post("/agents", json={"slug": f"agent-{index}", "name": f"Agent {index}"})

    first = client.get("/agents?limit=2").json()
    assert len(first["items"]) == 2
    assert first["total"] == 3
    assert first["has_more"] is True

    second = client.get("/agents?limit=2&offset=2").json()
    assert len(second["items"]) == 1
    assert second["has_more"] is False

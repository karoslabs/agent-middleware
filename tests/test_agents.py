from typing import Any

from fastapi.testclient import TestClient

from tests.test_models import make_model


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


def test_create_persists_the_catalog_fields_it_accepts(client: TestClient) -> None:
    """Everything ``AgentCreate`` declares survives the POST that carried it.

    ``create`` used to assemble its document from a hand-written list of fields
    that stopped at ``tags``, so the catalog half of the schema -- what the
    portal renders -- was accepted with a 201 and silently discarded. Only a
    follow-up PATCH stored it. Read back through GET rather than trusting the
    201 body: the response is built from the same dict that was written, so an
    echo proves nothing about what landed in Firestore.
    """

    stages = [
        {"id": "01-draft", "label": "Draft", "kind": "agent", "skill_ref": "draft@3"},
        {"id": "02-verify", "label": "Verify", "kind": "gate", "is_gate": True},
    ]
    required_inputs = [
        {"key": "topic", "type": "text", "label": "Topic", "required": True}
    ]
    created = client.post(
        "/agents",
        json={
            "slug": "catalog-writer",
            "name": "Catalog Writer",
            "icon": "pen-line",
            "category": "content",
            "credit_cost": 12,
            "is_public": False,
            "required_inputs": required_inputs,
            "stages": stages,
            "stages_read_only": False,
        },
    )
    assert created.status_code == 201, created.text

    stored = client.get("/agents/catalog-writer")
    assert stored.status_code == 200, stored.text
    body = stored.json()
    assert body["icon"] == "pen-line"
    assert body["category"] == "content"
    assert body["credit_cost"] == 12
    assert body["is_public"] is False
    assert body["stages_read_only"] is False
    assert [stage["id"] for stage in body["stages"]] == ["01-draft", "02-verify"]
    assert body["stages"][0]["skill_ref"] == "draft@3"
    assert body["stages"][1]["is_gate"] is True
    assert [item["key"] for item in body["required_inputs"]] == ["topic"]


def test_create_validates_stage_models_the_way_update_does(client: TestClient) -> None:
    """A stage cannot smuggle an unroutable model in through create.

    The gate ``update`` runs is only worth having if it cannot be walked around,
    and a POST that persists stages without it is exactly that walk-around.
    """

    make_model(client, model_id="claude-haiku-4-5", provider_model_name="claude-haiku-4-5")

    refused = client.post(
        "/agents",
        json={
            "slug": "typo-writer",
            "name": "Typo Writer",
            "stages": [
                {"id": "01-draft", "label": "Draft", "kind": "agent", "model_id": "claude-nope"}
            ],
        },
    )
    # 409, matching what the same validation returns from PATCH.
    assert refused.status_code == 409, refused.text
    assert "claude-nope" in refused.json()["detail"]
    # Rejected before the write, so the slug is still free.
    assert client.get("/agents/typo-writer").status_code == 404

    accepted = client.post(
        "/agents",
        json={
            "slug": "real-writer",
            "name": "Real Writer",
            "stages": [
                {
                    "id": "01-draft",
                    "label": "Draft",
                    "kind": "agent",
                    "model_id": "claude-haiku-4-5",
                }
            ],
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["stages"][0]["model_id"] == "claude-haiku-4-5"

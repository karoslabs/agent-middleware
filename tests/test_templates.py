from typing import Any

from fastapi.testclient import TestClient


def test_create_template_with_inline_first_version(
    client: TestClient, template: dict[str, Any]
) -> None:
    detail = client.get(f"/templates/{template['id']}").json()

    assert detail["id"] == "post-card"
    assert detail["kind"] == "html_layout"
    assert detail["active_version"]["version"] == 1
    assert detail["active_version"]["content"] == "<article>{{body}}</article>"
    assert detail["active_version"]["schema_definition"] == {"fields": ["body"]}
    assert [version["version"] for version in detail["versions"]] == [1]


def test_template_without_body_has_no_active_version(client: TestClient) -> None:
    created = client.post("/templates", json={"slug": "empty", "name": "Empty"})
    assert created.status_code == 201

    detail = client.get("/templates/empty").json()
    assert detail["active_version"] is None
    assert detail["versions"] == []


def test_duplicate_template_slug_is_rejected(
    client: TestClient, template: dict[str, Any]
) -> None:
    duplicate = client.post("/templates", json={"slug": template["slug"], "name": "Again"})

    assert duplicate.status_code == 409


def test_version_requires_a_body(client: TestClient, template: dict[str, Any]) -> None:
    response = client.post(f"/templates/{template['id']}/versions", json={"notes": "empty"})

    assert response.status_code == 422


def test_new_version_supersedes_and_can_be_rolled_back(
    client: TestClient, template: dict[str, Any]
) -> None:
    second = client.post(
        f"/templates/{template['id']}/versions",
        json={"content": "<section>{{body}}</section>", "notes": "restyled"},
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2

    detail = client.get(f"/templates/{template['id']}").json()
    assert detail["active_version"]["version"] == 2
    assert [version["version"] for version in detail["versions"]] == [2, 1]

    rolled_back = client.post(f"/templates/{template['id']}/versions/1/activate")
    assert rolled_back.json()["version"] == 1
    assert client.get(f"/templates/{template['id']}").json()["active_version"]["version"] == 1


def test_metadata_update_and_logical_delete(
    client: TestClient, template: dict[str, Any]
) -> None:
    patched = client.patch(
        f"/templates/{template['id']}", json={"name": "Post Card v2", "tags": ["social"]}
    )
    assert patched.json()["name"] == "Post Card v2"
    assert patched.json()["tags"] == ["social"]

    deleted = client.delete(f"/templates/{template['id']}")
    assert deleted.json()["deleted_at"] is not None
    assert client.get(f"/templates/{template['id']}").status_code == 404
    assert client.get("/templates").json()["total"] == 0

    restored = client.post(f"/templates/{template['id']}/restore")
    assert restored.json()["deleted_at"] is None
    assert client.get("/templates").json()["total"] == 1


def test_list_templates_filters_by_kind_and_query(client: TestClient) -> None:
    client.post("/templates", json={"slug": "layout", "name": "Layout", "kind": "html_layout"})
    client.post(
        "/templates", json={"slug": "structure", "name": "Structure", "kind": "json_schema"}
    )

    by_kind = client.get("/templates?kind=json_schema").json()
    assert [item["id"] for item in by_kind["items"]] == ["structure"]

    by_query = client.get("/templates?q=layout").json()
    assert [item["id"] for item in by_query["items"]] == ["layout"]


def test_bind_template_to_agent_is_idempotent_per_purpose(
    client: TestClient, agent: dict[str, Any], template: dict[str, Any]
) -> None:
    bound = client.put(
        f"/agents/{agent['id']}/templates/primary", json={"template_ref": template["id"]}
    )
    assert bound.status_code == 200
    assert bound.json()["template_id"] == template["id"]
    assert bound.json()["purpose"] == "primary"

    client.post("/templates", json={"slug": "other", "name": "Other", "content": "<p></p>"})
    rebound = client.put(
        f"/agents/{agent['id']}/templates/primary", json={"template_ref": "other"}
    )
    assert rebound.json()["template_id"] == "other"

    links = client.get(f"/agents/{agent['id']}/templates").json()
    assert len(links) == 1
    assert links[0]["template_id"] == "other"
    assert links[0]["template"]["name"] == "Other"


def test_bind_unknown_template_returns_404(
    client: TestClient, agent: dict[str, Any]
) -> None:
    response = client.put(
        f"/agents/{agent['id']}/templates/primary", json={"template_ref": "ghost"}
    )

    assert response.status_code == 404


def test_unbind_template(
    client: TestClient, agent: dict[str, Any], template: dict[str, Any]
) -> None:
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": template["id"]})

    removed = client.delete(f"/agents/{agent['id']}/templates/primary")
    assert removed.status_code == 200
    assert client.get(f"/agents/{agent['id']}/templates").json() == []
    assert client.delete(f"/agents/{agent['id']}/templates/primary").status_code == 404


def test_several_purposes_can_coexist(
    client: TestClient, agent: dict[str, Any], template: dict[str, Any]
) -> None:
    client.post("/templates", json={"slug": "email", "name": "Email", "content": "<html></html>"})

    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": template["id"]})
    client.put(f"/agents/{agent['id']}/templates/email", json={"template_ref": "email"})

    links = client.get(f"/agents/{agent['id']}/templates").json()
    assert {link["purpose"]: link["template_id"] for link in links} == {
        "email": "email",
        "primary": "post-card",
    }

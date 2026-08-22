from typing import Any

from fastapi.testclient import TestClient


def test_first_prompt_is_version_one_and_active(
    client: TestClient, agent: dict[str, Any]
) -> None:
    active = client.get(f"/agents/{agent['id']}/prompts/active")

    assert active.status_code == 200
    body = active.json()
    assert body["version"] == 1
    assert body["is_active"] is True
    assert body["agent_id"] == agent["id"]


def test_new_version_supersedes_the_previous_one(
    client: TestClient, agent: dict[str, Any]
) -> None:
    second = client.post(
        f"/agents/{agent['id']}/prompts",
        json={"content": "Write in Hebrew.", "notes": "localized", "variables": ["topic"]},
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2

    assert client.get(f"/agents/{agent['id']}/prompts/active").json()["version"] == 2
    assert client.get(f"/agents/{agent['id']}/prompts/1").json()["is_active"] is False

    versions = client.get(f"/agents/{agent['id']}/prompts").json()
    assert [version["version"] for version in versions] == [2, 1]


def test_version_can_be_added_without_activating(
    client: TestClient, agent: dict[str, Any]
) -> None:
    draft = client.post(
        f"/agents/{agent['id']}/prompts",
        json={"content": "Draft only.", "activate": False},
    )

    assert draft.json()["is_active"] is False
    assert client.get(f"/agents/{agent['id']}/prompts/active").json()["version"] == 1


def test_activating_an_older_version_rolls_back(
    client: TestClient, agent: dict[str, Any]
) -> None:
    client.post(f"/agents/{agent['id']}/prompts", json={"content": "v2"})

    rolled_back = client.post(f"/agents/{agent['id']}/prompts/1/activate")

    assert rolled_back.status_code == 200
    assert rolled_back.json()["version"] == 1
    assert client.get(f"/agents/{agent['id']}/prompts/active").json()["version"] == 1
    assert client.get(f"/agents/{agent['id']}/prompts/2").json()["is_active"] is False


def test_unknown_prompt_version_returns_404(client: TestClient, agent: dict[str, Any]) -> None:
    assert client.get(f"/agents/{agent['id']}/prompts/99").status_code == 404


def test_prompt_routes_require_a_known_agent(client: TestClient) -> None:
    response = client.post("/agents/ghost/prompts", json={"content": "hello"})

    assert response.status_code == 404


def test_agent_with_no_prompt_has_no_active_version(client: TestClient) -> None:
    client.post("/agents", json={"slug": "bare", "name": "Bare"})

    assert client.get("/agents/bare/prompts/active").status_code == 404
    assert client.get("/agents/bare/prompts").json() == []


def test_example_crud_and_ordering(client: TestClient, agent: dict[str, Any]) -> None:
    second = client.post(
        f"/agents/{agent['id']}/examples",
        json={"user_input": "b", "assistant_output": "B", "position": 2},
    )
    first = client.post(
        f"/agents/{agent['id']}/examples",
        json={"user_input": "a", "assistant_output": "A", "position": 1, "tags": ["gold"]},
    )
    assert first.status_code == 201
    assert first.json()["source"] == "manual"

    listed = client.get(f"/agents/{agent['id']}/examples").json()
    assert [item["user_input"] for item in listed["items"]] == ["a", "b"]
    assert listed["total"] == 2

    tagged = client.get(f"/agents/{agent['id']}/examples?tag=gold").json()
    assert [item["id"] for item in tagged["items"]] == [first.json()["id"]]

    patched = client.patch(
        f"/agents/{agent['id']}/examples/{second.json()['id']}",
        json={"is_active": False, "label": "retired"},
    )
    assert patched.json()["is_active"] is False
    assert patched.json()["label"] == "retired"
    assert patched.json()["assistant_output"] == "B"

    active_only = client.get(f"/agents/{agent['id']}/examples?active_only=true").json()
    assert [item["user_input"] for item in active_only["items"]] == ["a"]

    deleted = client.delete(f"/agents/{agent['id']}/examples/{second.json()['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/agents/{agent['id']}/examples").json()["total"] == 1


def test_unknown_example_returns_404(client: TestClient, agent: dict[str, Any]) -> None:
    assert client.get(f"/agents/{agent['id']}/examples/missing").status_code == 404
    assert client.delete(f"/agents/{agent['id']}/examples/missing").status_code == 404

from typing import Any

from fastapi.testclient import TestClient


def test_context_resolves_prompt_examples_and_template(
    client: TestClient, agent: dict[str, Any], template: dict[str, Any]
) -> None:
    client.post(
        f"/agents/{agent['id']}/examples",
        json={"user_input": "topic: coffee", "assistant_output": "Coffee post", "position": 1},
    )
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": template["id"]})

    response = client.get(f"/agents/{agent['id']}/context")

    assert response.status_code == 200
    context = response.json()
    assert context["agent"]["id"] == agent["id"]
    assert context["agent"]["model"] == "claude-opus-5"
    assert context["agent"]["model_params"] == {"temperature": 0.4}
    assert context["system_prompt"]["version"] == 1
    assert context["system_prompt"]["content"].startswith("You are a concise")
    assert [example["user_input"] for example in context["few_shot_examples"]] == [
        "topic: coffee"
    ]
    assert context["template"]["id"] == template["id"]
    assert context["template"]["version"] == 1
    assert context["template"]["purpose"] == "primary"
    assert context["template"]["content"] == "<article>{{body}}</article>"
    assert context["resolved_at"]


def test_context_reflects_the_newest_active_prompt(
    client: TestClient, agent: dict[str, Any]
) -> None:
    client.post(f"/agents/{agent['id']}/prompts", json={"content": "Newer instructions."})

    context = client.get(f"/agents/{agent['id']}/context").json()

    assert context["system_prompt"]["version"] == 2
    assert context["system_prompt"]["content"] == "Newer instructions."


def test_context_without_template_binding_is_still_valid(
    client: TestClient, agent: dict[str, Any]
) -> None:
    context = client.get(f"/agents/{agent['id']}/context").json()

    assert context["template"] is None
    assert context["system_prompt"] is not None


def test_context_excludes_inactive_examples_and_honours_the_cap(
    client: TestClient, agent: dict[str, Any]
) -> None:
    for index in range(3):
        client.post(
            f"/agents/{agent['id']}/examples",
            json={
                "user_input": f"in-{index}",
                "assistant_output": f"out-{index}",
                "position": index,
            },
        )
    retired = client.post(
        f"/agents/{agent['id']}/examples",
        json={"user_input": "old", "assistant_output": "old", "position": 99},
    ).json()
    client.patch(f"/agents/{agent['id']}/examples/{retired['id']}", json={"is_active": False})

    context = client.get(f"/agents/{agent['id']}/context?max_examples=2").json()
    assert [example["user_input"] for example in context["few_shot_examples"]] == [
        "in-0",
        "in-1",
    ]

    without = client.get(f"/agents/{agent['id']}/context?include_examples=false").json()
    assert without["few_shot_examples"] == []

    everything = client.get(f"/agents/{agent['id']}/context").json()
    assert [example["user_input"] for example in everything["few_shot_examples"]] == [
        "in-0",
        "in-1",
        "in-2",
    ]


def test_template_query_parameter_overrides_the_binding(
    client: TestClient, agent: dict[str, Any], template: dict[str, Any]
) -> None:
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": template["id"]})
    client.post("/templates", json={"slug": "one-off", "name": "One Off", "content": "<b></b>"})

    context = client.get(f"/agents/{agent['id']}/context?template=one-off").json()

    assert context["template"]["id"] == "one-off"


def test_context_of_a_template_without_active_version_conflicts(
    client: TestClient, agent: dict[str, Any]
) -> None:
    client.post("/templates", json={"slug": "bodyless", "name": "Bodyless"})
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": "bodyless"})

    response = client.get(f"/agents/{agent['id']}/context")

    assert response.status_code == 409
    assert "no active version" in response.json()["detail"]


def test_context_of_a_disabled_agent_is_readable_but_not_runnable(
    client: TestClient, agent: dict[str, Any]
) -> None:
    client.patch(f"/agents/{agent['id']}/status", json={"status": "disabled"})

    assert client.get(f"/agents/{agent['id']}/context").status_code == 200

    response = client.get(f"/agents/{agent['id']}/context?require_active=true")
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]


def test_context_of_unknown_agent_returns_404(client: TestClient) -> None:
    assert client.get("/agents/ghost/context").status_code == 404

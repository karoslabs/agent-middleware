import json
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import FakePublisherClient


def test_dispatch_publishes_payload_and_records_run(
    client: TestClient,
    agent: dict[str, Any],
    template: dict[str, Any],
    fake_publisher_client: FakePublisherClient,
) -> None:
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": template["id"]})
    client.post(
        f"/agents/{agent['id']}/examples",
        json={"user_input": "topic: tea", "assistant_output": "Tea post"},
    )

    response = client.post(
        f"/agents/{agent['id']}/jobs",
        json={
            "job_type": "social_post",
            "input": {"topic": "cold brew"},
            "requested_by": "portal",
        },
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["topic"] == "projects/test-project/topics/test-jobs-topic"
    assert body["run"]["status"] == "dispatched"
    assert body["run"]["pubsub_message_id"] == body["pubsub_message_id"]
    assert body["run"]["prompt_version"] == 1
    assert body["run"]["job_type"] == "social_post"
    assert body["run"]["requested_by"] == "portal"

    topic, data, attributes = fake_publisher_client.published[0]
    assert topic == "projects/test-project/topics/test-jobs-topic"

    payload = json.loads(data.decode("utf-8"))
    assert payload["schema_version"] == 1
    assert payload["run_id"] == body["run"]["id"]
    assert payload["input"] == {"topic": "cold brew"}
    assert payload["agent"]["slug"] == agent["slug"]
    assert payload["system_prompt"]["version"] == 1
    assert payload["template"]["content"] == "<article>{{body}}</article>"
    assert [example["user_input"] for example in payload["few_shot_examples"]] == ["topic: tea"]

    assert attributes["run_id"] == body["run"]["id"]
    assert attributes["agent_slug"] == agent["slug"]
    assert attributes["job_type"] == "social_post"
    assert attributes["prompt_version"] == "1"
    assert attributes["template_version"] == "1"
    assert attributes["source"] == "agent-middleware"


def test_run_snapshot_references_versions_instead_of_copying_bodies(
    client: TestClient, agent: dict[str, Any], template: dict[str, Any]
) -> None:
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": template["id"]})

    run = client.post(
        f"/agents/{agent['id']}/jobs", json={"input": {"topic": "matcha"}}
    ).json()["run"]

    assert run["input_payload"] == {
        "input": {"topic": "matcha"},
        "template_purpose": "primary",
        "example_count": 0,
        "template_id": template["id"],
        "template_version": 1,
    }
    assert run["template_version_id"] is not None


def test_caller_supplied_run_id_is_used(client: TestClient, agent: dict[str, Any]) -> None:
    response = client.post(f"/agents/{agent['id']}/jobs", json={"run_id": "portal-run-1"})

    assert response.json()["run"]["id"] == "portal-run-1"
    assert client.get(f"/agents/{agent['id']}/runs/portal-run-1").status_code == 200


def test_duplicate_run_id_is_rejected(client: TestClient, agent: dict[str, Any]) -> None:
    client.post(f"/agents/{agent['id']}/jobs", json={"run_id": "portal-run-1"})

    duplicate = client.post(f"/agents/{agent['id']}/jobs", json={"run_id": "portal-run-1"})

    assert duplicate.status_code == 409


def test_caller_attributes_cannot_override_routing_attributes(
    client: TestClient, agent: dict[str, Any], fake_publisher_client: FakePublisherClient
) -> None:
    client.post(
        f"/agents/{agent['id']}/jobs",
        json={"run_id": "run-x", "attributes": {"run_id": "spoofed", "tenant": "acme"}},
    )

    _, _, attributes = fake_publisher_client.published[0]
    assert attributes["run_id"] == "run-x"
    assert attributes["tenant"] == "acme"


def test_dispatch_requires_an_active_prompt(client: TestClient) -> None:
    client.post("/agents", json={"slug": "bare", "name": "Bare"})

    response = client.post("/agents/bare/jobs", json={})

    assert response.status_code == 422
    assert "no active system prompt" in response.json()["detail"]


def test_dispatch_refuses_a_disabled_agent(client: TestClient, agent: dict[str, Any]) -> None:
    client.patch(f"/agents/{agent['id']}/status", json={"status": "disabled"})

    response = client.post(f"/agents/{agent['id']}/jobs", json={})

    assert response.status_code == 409


def test_payload_preview_publishes_nothing(
    client: TestClient, agent: dict[str, Any], fake_publisher_client: FakePublisherClient
) -> None:
    response = client.post(
        f"/agents/{agent['id']}/payload", json={"input": {"topic": "preview"}}
    )

    assert response.status_code == 200
    assert response.json()["input"] == {"topic": "preview"}
    assert response.json()["run_id"] == "preview"
    assert fake_publisher_client.published == []
    assert client.get(f"/agents/{agent['id']}/runs").json()["items"] == []


def test_failed_publish_marks_the_run_failed(
    client: TestClient, agent: dict[str, Any], fake_publisher_client: FakePublisherClient
) -> None:
    def explode(topic: str, data: bytes, **attributes: str) -> None:
        raise RuntimeError("pubsub unavailable")

    fake_publisher_client.publish = explode  # type: ignore[method-assign]

    response = client.post(f"/agents/{agent['id']}/jobs", json={"run_id": "doomed"})

    assert response.status_code == 502
    run = client.get(f"/agents/{agent['id']}/runs/doomed").json()
    assert run["status"] == "failed"
    assert "pubsub unavailable" in run["error"]
    assert run["completed_at"] is not None

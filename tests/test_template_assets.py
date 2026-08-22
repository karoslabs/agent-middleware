"""GCS asset URIs bound to a template version, and their trip into a job payload.

Firestore holds the text (bodies, schemas); binaries live in GCS and only their
``gs://`` references travel. These tests pin that the reference survives every
hop the engine depends on: create -> version row -> resolved context ->
dispatched payload.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

LOGO = "gs://karoscmo-prep-agent-artifacts/templates/post-card/logo.svg"
FONT = "gs://karoscmo-prep-agent-artifacts/templates/post-card/Inter.woff2"


def test_assets_are_stored_on_the_initial_version(client: TestClient) -> None:
    response = client.post(
        "/templates",
        json={
            "slug": "with-assets",
            "name": "With Assets",
            "kind": "html_layout",
            "content": "<article>{{body}}</article>",
            "assets": [LOGO, FONT],
        },
    )
    assert response.status_code == 201, response.text

    detail = client.get("/templates/with-assets").json()
    assert detail["active_version"]["assets"] == [LOGO, FONT]


def test_assets_are_versioned_with_the_body(client: TestClient, template: dict[str, Any]) -> None:
    """A rollback restores the asset set the body was authored against."""

    v2 = client.post(
        f"/templates/{template['id']}/versions",
        json={"content": "<article class='v2'>{{body}}</article>", "assets": [LOGO]},
    )
    assert v2.status_code == 201, v2.text
    assert v2.json()["version"] == 2
    assert v2.json()["assets"] == [LOGO]

    # v1 was created without assets and must not retroactively gain them.
    v1 = client.get(f"/templates/{template['id']}/versions/1").json()
    assert v1["assets"] == []


def test_a_version_without_assets_reads_back_as_an_empty_list(
    client: TestClient, template: dict[str, Any]
) -> None:
    """Absent is empty, never null — the engine iterates this without a guard."""

    detail = client.get(f"/templates/{template['id']}").json()
    assert detail["active_version"]["assets"] == []


def test_non_gcs_asset_uris_are_refused(client: TestClient) -> None:
    for bad in ["https://cdn.example.com/logo.svg", "logo.svg", "/tmp/logo.svg", "gs://"]:
        response = client.post(
            "/templates",
            json={
                "slug": f"bad-{abs(hash(bad))}",
                "name": "Bad",
                "content": "<p></p>",
                "assets": [bad],
            },
        )
        assert response.status_code == 422, f"{bad!r} should have been refused"


def test_assets_are_bundled_into_the_resolved_context(
    client: TestClient, agent: dict[str, Any]
) -> None:
    client.post(
        "/templates",
        json={
            "slug": "carousel",
            "name": "Carousel",
            "kind": "html_layout",
            "content": "<section>{{slide}}</section>",
            "assets": [LOGO, FONT],
        },
    )
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": "carousel"})

    context = client.get(f"/agents/{agent['id']}/context").json()

    assert context["template"]["assets"] == [LOGO, FONT]


def test_assets_reach_the_dispatched_job_payload(
    client: TestClient,
    agent: dict[str, Any],
    fake_publisher_client: Any,
) -> None:
    """The engine reads assets off the message, so they must be in the message."""

    client.post(
        "/templates",
        json={
            "slug": "carousel",
            "name": "Carousel",
            "kind": "html_layout",
            "content": "<section>{{slide}}</section>",
            "assets": [LOGO],
        },
    )
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": "carousel"})

    dispatched = client.post(
        f"/agents/{agent['id']}/jobs", json={"client_slug": "acme", "input": {"topic": "coffee"}}
    )
    assert dispatched.status_code == 202, dispatched.text

    import json

    _topic, data, _attributes = fake_publisher_client.published[-1]
    payload = json.loads(data)
    assert payload["template"]["assets"] == [LOGO]


def test_preview_shows_the_assets_a_dispatch_would_carry(
    client: TestClient, agent: dict[str, Any]
) -> None:
    client.post(
        "/templates",
        json={
            "slug": "carousel",
            "name": "Carousel",
            "content": "<section></section>",
            "assets": [LOGO],
        },
    )
    client.put(f"/agents/{agent['id']}/templates/primary", json={"template_ref": "carousel"})

    payload = client.post(f"/agents/{agent['id']}/payload", json={"client_slug": "acme"}).json()

    assert payload["template"]["assets"] == [LOGO]

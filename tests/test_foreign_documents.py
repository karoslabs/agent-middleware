"""Listings must survive documents this service did not write.

Not hypothetical. prep's Firestore ``agents/`` collection already holds rows
from karosCMO's since-removed in-app agent engine — camelCase ``systemPrompt``
/ ``outputKind`` / ``runCount``, no ``slug``, no ``created_at``. Before
``parse_rows`` those two dead documents made ``GET /agents`` return 500 and hid
every legitimate agent behind them.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.firestore import AGENTS, TEMPLATES, FirestoreDB

# Verbatim shape of the real offender found in prep.
LEGACY_KAROSCMO_AGENT: dict[str, Any] = {
    "name": "Intel Report Agent",
    "description": "Automated Digital Intelligence",
    "systemPrompt": "You are the Karos Intel AI",
    "outputKind": "freeform",
    "capabilities": ["generate"],
    "isActive": True,
    "isSystem": True,
    "runCount": 0,
    "color": "#C8FF00",
    "icon": "BarChart2",
    "status": "published",
    "createdAt": 1783526131675,
    "updatedAt": 1783526131675,
}


async def _write_foreign_agent(database: FirestoreDB) -> None:
    await database.document(AGENTS, "intel-report-agent").set(LEGACY_KAROSCMO_AGENT)


async def test_agent_listing_survives_a_foreign_document(
    client: TestClient, agent: dict[str, Any], database: FirestoreDB
) -> None:
    await _write_foreign_agent(database)

    response = client.get("/agents")

    assert response.status_code == 200, response.text
    slugs = [item["slug"] for item in response.json()["items"]]
    # The real agent is still listed; the foreign row is skipped, not fatal.
    assert agent["slug"] in slugs
    assert "intel-report-agent" not in slugs


async def test_template_listing_survives_a_foreign_document(
    client: TestClient, template: dict[str, Any], database: FirestoreDB
) -> None:
    await database.document(TEMPLATES, "legacy-thing").set({"someOtherSchema": True})

    response = client.get("/templates")

    assert response.status_code == 200, response.text
    assert [item["slug"] for item in response.json()["items"]] == [template["slug"]]


async def test_fetching_a_foreign_document_by_id_still_errors(
    client: TestClient, database: FirestoreDB
) -> None:
    """Skipping is for listings only.

    Asking for one specific document and getting a cheerful 200 with invented
    fields would be worse than an error — the caller asked about *that* row.
    """

    await _write_foreign_agent(database)

    response = client.get("/agents/intel-report-agent")

    assert response.status_code >= 400


async def test_a_skipped_row_is_logged_loudly(
    client: TestClient, database: FirestoreDB, caplog: pytest.LogCaptureFixture
) -> None:
    """Degrading quietly would turn a data problem into a mystery."""

    await _write_foreign_agent(database)

    with caplog.at_level("WARNING"):
        response = client.get("/agents")

    assert response.status_code == 200
    assert any("intel-report-agent" in record.getMessage() for record in caplog.records)


async def test_a_listing_of_only_foreign_documents_is_empty_not_broken(
    client: TestClient, database: FirestoreDB
) -> None:
    await _write_foreign_agent(database)

    response = client.get("/agents")

    assert response.status_code == 200
    assert response.json()["items"] == []

"""The legacy migration script.

Split in two. The pure helpers (frontmatter stripping, harness detection,
normalisation) are tested unconditionally. The end-to-end seed runs against the
in-memory Firestore and needs a real ``karos-agents`` checkout, so it skips when
one isn't beside this repo — the same reason the manifest names real paths
instead of globbing.

The property that actually matters here is idempotency: prompt and template
versions are append-only, so a re-run that isn't content-compared would stack a
v2, v3, v4 of byte-identical bodies and quietly corrupt the version history that
feedback attribution depends on.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from app.config import Settings
from app.db.firestore import FirestoreDB
from app.services.agents import AgentService
from app.services.prompts import PromptService
from app.services.templates import TemplateService
from scripts.legacy_manifest import AGENT_SPECS
from scripts.seed_legacy_agents import (
    AssetUploader,
    Report,
    Seeder,
    build_settings,
    find_claude_isms,
    normalized,
    strip_frontmatter,
)
from tests.fake_firestore import FakeFirestoreClient

KAROS_AGENTS = Path(__file__).resolve().parent.parent.parent / "karos-agents"
needs_lab_repo = pytest.mark.skipif(
    not KAROS_AGENTS.is_dir(), reason="karos-agents checkout not found beside this repo"
)


# --- Pure helpers -----------------------------------------------------------


def test_strip_frontmatter_removes_a_leading_yaml_block() -> None:
    text = "---\nname: karos-x-agent\ntriggers:\n  - /x-agent\n---\n\n# Heading\n\nBody."

    assert strip_frontmatter(text) == "# Heading\n\nBody."


def test_strip_frontmatter_leaves_a_body_without_frontmatter_alone() -> None:
    text = "# Heading\n\nBody with --- a dash rule in it.\n"

    assert strip_frontmatter(text) == text


def test_strip_frontmatter_only_removes_the_first_block() -> None:
    """A `---` rule inside the body is content, not a second frontmatter."""

    text = "---\nname: a\n---\n\nIntro.\n\n---\n\nStill body.\n"

    stripped = strip_frontmatter(text)
    assert stripped.startswith("Intro.")
    assert "Still body." in stripped


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("dispatch via the Task tool with subagent_type: research", "Claude Task-tool fan-out"),
        ("fall back to WebSearch when the feed is stale", "Claude built-in tool reference"),
        ("model: claude-opus-4-8", "hardcoded model id"),
        ("never write to ~/.claude/skills/", "Claude Skills path assumption"),
        ("Claude Preview MCP screenshots the page", "Claude-specific MCP tool"),
        ("call it with max_tokens: 2000", "provider-specific sampling parameter"),
    ],
)
def test_harness_specific_content_is_detected(text: str, expected: str) -> None:
    assert expected in find_claude_isms(text)


def test_clean_prose_produces_no_warnings() -> None:
    text = "Write one post. Cite every number. Never invent a statistic."

    assert find_claude_isms(text) == []


def test_normalized_ignores_line_endings_and_trailing_space() -> None:
    assert normalized("a  \r\nb\n") == normalized("a\nb")
    assert normalized(None) == ""


def test_environment_presets_target_the_right_databases() -> None:
    prep = build_settings(argparse.Namespace(env="prep", firestore_database=None, bucket=None))
    prod = build_settings(argparse.Namespace(env="prod", firestore_database=None, bucket=None))

    assert (prep.resolved_firestore_project_id, prep.firestore_database) == ("karoscmo", "prep")
    assert (prod.resolved_firestore_project_id, prod.firestore_database) == (
        "karoscmo",
        "(default)",
    )
    # A seed script has no business serving requests.
    assert prep.auth_enabled is False


# --- End to end against the in-memory store ---------------------------------


def _seeder(database: FirestoreDB, report: Report) -> Seeder:
    return Seeder(
        root=KAROS_AGENTS,
        agents=AgentService(database),
        prompts=PromptService(database),
        templates=TemplateService(database),
        uploader=AssetUploader("test-bucket", enabled=False, report=report),
        report=report,
        dry_run=False,
    )


@pytest.fixture
def seed_database() -> FirestoreDB:
    settings = Settings(
        gcp_project_id="test-project",
        pubsub_job_topic_id="test-jobs",
        gcs_artifacts_bucket="test-bucket",
        auth_enabled=False,
    )
    return FirestoreDB(settings, client=FakeFirestoreClient())  # type: ignore[arg-type]


@needs_lab_repo
async def test_first_seed_creates_every_agent_in_the_manifest(seed_database: FirestoreDB) -> None:
    report = Report()
    await _seeder(seed_database, report).seed_all()

    agents = AgentService(seed_database)
    for spec in AGENT_SPECS:
        agent = await agents.get(spec.slug)
        assert agent["name"] == spec.name
        assert agent["agent_type"] == spec.agent_type

    assert report.counts["created"] > 0
    assert report.counts["updated"] == 0


@needs_lab_repo
async def test_seeding_twice_changes_nothing(seed_database: FirestoreDB) -> None:
    """The whole point: a re-run must not append duplicate versions."""

    await _seeder(seed_database, Report()).seed_all()

    second = Report()
    await _seeder(seed_database, second).seed_all()

    assert second.counts["created"] == 0, "second run created something"
    assert second.counts["updated"] == 0, "second run updated something"
    assert second.counts["unchanged"] > 0


@needs_lab_repo
async def test_re_seeding_leaves_exactly_one_prompt_version(
    seed_database: FirestoreDB,
) -> None:
    await _seeder(seed_database, Report()).seed_all()
    await _seeder(seed_database, Report()).seed_all()
    await _seeder(seed_database, Report()).seed_all()

    prompts = PromptService(seed_database)
    for spec in AGENT_SPECS:
        versions = await prompts.list_versions(spec.slug)
        assert len(versions) == 1, f"{spec.slug} accumulated {len(versions)} prompt versions"
        assert versions[0]["is_active"] is True


@needs_lab_repo
async def test_a_changed_source_produces_a_second_version(
    seed_database: FirestoreDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Idempotency must not mean 'never updates' — real edits still land."""

    await _seeder(seed_database, Report()).seed_all()

    import scripts.seed_legacy_agents as seed_module

    original = seed_module.compose_prompt
    monkeypatch.setattr(
        seed_module,
        "compose_prompt",
        lambda root, spec: original(root, spec) + "\n\nA newly added house rule.\n",
    )

    report = Report()
    await _seeder(seed_database, report).seed_all()

    assert report.counts["updated"] == len(AGENT_SPECS)

    versions = await PromptService(seed_database).list_versions(AGENT_SPECS[0].slug)
    assert len(versions) == 2
    # Newest first, and only the new one is active.
    assert versions[0]["version"] == 2
    assert versions[0]["is_active"] is True
    assert versions[1]["is_active"] is False


@needs_lab_repo
async def test_templates_are_bound_to_their_declared_purposes(
    seed_database: FirestoreDB,
) -> None:
    await _seeder(seed_database, Report()).seed_all()

    templates = TemplateService(seed_database)
    for spec in AGENT_SPECS:
        for source in spec.templates:
            if source.purpose is None:
                continue
            resolved = await templates.resolve_for_agent(spec.slug, purpose=source.purpose)
            assert resolved is not None, f"{spec.slug}/{source.purpose} did not resolve"
            template, version = resolved
            assert template["id"] == source.slug
            assert version["is_active"] is True


@needs_lab_repo
async def test_seeded_agents_resolve_into_a_runnable_context(
    seed_database: FirestoreDB,
) -> None:
    """The real acceptance test: can a seeded agent actually be dispatched?"""

    from app.services.context import ContextService

    settings = Settings(
        gcp_project_id="test-project",
        pubsub_job_topic_id="test-jobs",
        auth_enabled=False,
    )
    await _seeder(seed_database, Report()).seed_all()

    context_service = ContextService(
        settings,
        AgentService(seed_database),
        PromptService(seed_database),
        TemplateService(seed_database),
    )

    for spec in AGENT_SPECS:
        context = await context_service.build_runnable(spec.slug)
        assert context.system_prompt is not None
        assert context.system_prompt.content.strip()
        # Frontmatter must be gone by the time it reaches a payload.
        assert not context.system_prompt.content.startswith("---")


@needs_lab_repo
async def test_reddit_carries_its_draft_only_rule_into_the_context(
    seed_database: FirestoreDB,
) -> None:
    """Draft-only is a product rule; it has to travel with the agent."""

    await _seeder(seed_database, Report()).seed_all()

    agent = await AgentService(seed_database).get("reddit-agent")
    assert agent["config"]["draft_only"] is True
    assert agent["config"]["replies_only"] is True


# --- Upload preflight -------------------------------------------------------


def test_preflight_rejects_upload_without_a_bucket() -> None:
    """Catch an unusable upload config before the first Firestore write.

    A real run once discovered a missing dependency eleven documents in;
    idempotency made the resume clean, but a half-written store is not a state
    worth relying on recovering from.
    """

    uploader = AssetUploader(None, enabled=True, report=Report())

    with pytest.raises(RuntimeError, match="no bucket is configured"):
        uploader.preflight()


def test_preflight_is_a_no_op_when_uploads_are_disabled() -> None:
    AssetUploader(None, enabled=False, report=Report()).preflight()

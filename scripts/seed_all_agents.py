#!/usr/bin/env python3
"""Register every agent-engine workflow as a first-class control-plane agent.

Six of the eleven were seeded from the karos-agents lab repo, because that is
where their prompts came from. The other five have no lab source, so they
existed only as TypeScript in agent-engine and had no database row at all --
which is why the portal could not list them, price them, or open them in the
Studio.

This writes all eleven with the catalog/Studio contract: name, description,
icon, category, credit cost, the inputs a run dialog should ask for, and the
stages the workflow actually runs.

## Stages are read from code, not written here

``engine_stages.json`` is generated from agent-engine's own workflow sources by
walking every ``wf.step.code``/``.agent``/``.gate`` call. Hand-maintaining a
stage list beside a workflow that changes is how a Studio ends up describing a
program that no longer exists; generating it means the list is either right or
visibly stale.

Retry suffixes are collapsed -- ``05-write-copy-attempt-${attempt}`` is one
stage a workflow may run twice, not two stages.

## What this does NOT touch

Prompts. Those already exist for the six agents with a lab source, and
inventing a v1 for the other five would put words in a client's agent that no
one wrote. They get their row, their metadata and their model; their prompt
stays absent, which the Studio shows as "no prompt" rather than as a default
someone might mistake for reviewed copy.

Idempotent by content comparison: a re-run writes nothing when unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENVIRONMENTS: dict[str, str] = {"prep": "prep", "prod": "(default)"}
FIRESTORE_PROJECT = "karoscmo"
COLLECTION = "agents"
STAGES_FILE = Path(__file__).with_name("engine_stages.json")

#: Every hand-written workflow agent-engine can dispatch, with the metadata the
#: portal needs to render it. `model` references the normalized `models`
#: collection (see seed_models.py), never a loose vendor string.
CATALOG: tuple[dict[str, Any], ...] = (
    {
        "slug": "instagram-agent",
        "name": "Instagram Post / Carousel Creator",
        "description": (
            "Researches a topic, writes a six-to-eight slide carousel, sources and vets imagery, "
            "and renders the slides."
        ),
        "icon": "Camera",
        "category": "social",
        "credit_cost": 12,
        "agent_type": "instagram_carousel",
        "tags": ["social", "instagram", "carousel"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "What should this carousel cover?",
                "required": False,
                "placeholder": "Leave blank to let the agent pick from its topic pool",
            },
        ],
    },
    {
        "slug": "landing-builder-agent",
        "name": "Landing Page Builder",
        "description": (
            "Builds a complete landing page from the client's brand contract and intake, pausing "
            "for human review before delivery."
        ),
        "icon": "Layout",
        "category": "web",
        "credit_cost": 40,
        "agent_type": "landing_page",
        "tags": ["web", "landing-page", "gated"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Anything specific for this build?",
                "required": False,
            },
        ],
    },
    {
        "slug": "x-agent",
        "name": "X / Twitter Content Specialist",
        "description": (
            "Drafts one X post per run against the account's charter, with lane rotation, claim "
            "checks and brand-compliance gates."
        ),
        "icon": "AtSign",
        "category": "social",
        "credit_cost": 6,
        "agent_type": "x_post",
        "tags": ["social", "x", "draft-only"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Topic for this post",
                "required": False,
                "placeholder": "Leave blank to use the lane rotation",
            },
            {
                "key": "requestedLane",
                "type": "select",
                "label": "Lane",
                "required": False,
                "options": ["knowledge", "pov", "product", "engagement"],
            },
        ],
    },
    {
        "slug": "linkedin-agent",
        "name": "LinkedIn Thought Leadership Writer",
        "description": (
            "Drafts one LinkedIn post in the company voice or a named executive's, choosing from "
            "eleven founder archetypes."
        ),
        "icon": "Share2",
        "category": "social",
        "credit_cost": 8,
        "agent_type": "linkedin_post",
        "tags": ["social", "linkedin", "draft-only"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Topic for this post",
                "required": False,
            },
            {
                "key": "requestedIdentityScope",
                "type": "select",
                "label": "Post as",
                "required": False,
                "options": ["company", "executive"],
            },
        ],
    },
    {
        "slug": "reddit-agent",
        "name": "Reddit Community Post Writer",
        "description": (
            "Drafts ONE reply for a chosen thread, against that subreddit's rules. Draft-only by "
            "hard product rule -- a human always posts it."
        ),
        "icon": "MessageSquare",
        "category": "social",
        "credit_cost": 6,
        "agent_type": "reddit_reply",
        "tags": ["social", "reddit", "draft-only"],
        "required_inputs": [
            {
                "key": "requestedSubreddit",
                "type": "text",
                "label": "Subreddit",
                "required": False,
                "placeholder": "r/marketing",
            },
            {"key": "requestedThreadUrl", "type": "text", "label": "Thread URL", "required": False},
        ],
    },
    {
        "slug": "branded-shorts-agent",
        "name": "Branded Shorts Video Creator",
        "description": (
            "Cuts short-form video from a source recording, planning motion graphics from the "
            "transcript rather than from stock."
        ),
        "icon": "Video",
        "category": "video",
        "credit_cost": 45,
        "agent_type": "branded_shorts",
        "tags": ["video", "shorts"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Which recording, and what angle?",
                "required": True,
            },
        ],
    },
    {
        "slug": "intel-report-agent",
        "name": "Competitive Intelligence & Market Analysis",
        "description": (
            "Pulls competitive and market research for a client and writes it up as a structured "
            "intelligence report."
        ),
        "icon": "Search",
        "category": "research",
        "credit_cost": 25,
        "agent_type": "intel_report",
        "tags": ["research", "intel"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "What should this report focus on?",
                "required": False,
            },
        ],
    },
    {
        "slug": "blog-agent",
        "name": "SEO & Long-form Blog Writer",
        "description": (
            "Researches and writes a long-form article with an SEO structure, internal linking and "
            "a self-critique pass."
        ),
        "icon": "FileText",
        "category": "content",
        "credit_cost": 20,
        "agent_type": "blog_article",
        "tags": ["content", "blog", "seo"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Article topic or brief",
                "required": False,
            },
        ],
    },
    {
        "slug": "newsletter-agent",
        "name": "Email Newsletter & Campaign Writer",
        "description": (
            "Writes one newsletter issue from the client's recent material, with a compliance pass "
            "before delivery."
        ),
        "icon": "Mail",
        "category": "content",
        "credit_cost": 18,
        "agent_type": "newsletter_issue",
        "tags": ["content", "newsletter", "email"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Theme for this issue",
                "required": False,
            },
        ],
    },
    {
        "slug": "reputation-agent",
        "name": "Reputation Management & Review Responder",
        "description": (
            "Mines response behaviour, assesses reputation state and drafts replies. Publishing is "
            "permanently gated inside the workflow."
        ),
        "icon": "Shield",
        "category": "reputation",
        "credit_cost": 15,
        "agent_type": "reputation",
        "tags": ["reputation", "draft-only", "gated"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Anything to focus on?",
                "required": False,
            },
        ],
    },
    {
        "slug": "seo-geo-agent",
        "name": "Local SEO & Geo-targeted Content Specialist",
        "description": (
            "Captures search and answer-engine visibility for a client, finds the gaps and drafts "
            "the fixes."
        ),
        "icon": "MapPin",
        "category": "seo",
        "credit_cost": 22,
        "agent_type": "seo_geo",
        "tags": ["seo", "geo", "research"],
        "required_inputs": [
            {
                "key": "request",
                "type": "textarea",
                "label": "Which locations or queries?",
                "required": False,
            },
        ],
    },
    {
        "slug": "linkedin-setup-agent",
        "name": "LinkedIn Setup",
        "description": (
            "Records filled seat intake forms as the charters the LinkedIn writer reads. "
            "Onboarding, not drafting -- it runs no model."
        ),
        "icon": "UserPlus",
        "category": "onboarding",
        "credit_cost": 0,
        "agent_type": "linkedin_setup",
        "tags": ["onboarding", "linkedin"],
        "required_inputs": [
            {
                "key": "companyUpdates",
                "type": "textarea",
                "label": "Standing direction for the company page",
                "required": False,
            },
        ],
    },
    {
        "slug": "reddit-setup-agent",
        "name": "Reddit Setup",
        "description": (
            "Records which communities a client may post into, and how. Draft-only downstream: "
            "a human always posts the reply from their own account."
        ),
        "icon": "UserPlus",
        "category": "onboarding",
        "credit_cost": 0,
        "agent_type": "reddit_setup",
        "tags": ["onboarding", "reddit"],
        "required_inputs": [
            {
                "key": "targetSubreddits",
                "type": "text",
                "label": "Subreddits (comma separated)",
                "required": True,
                "placeholder": "r/marketing, r/SaaS",
            },
        ],
    },
)

#: Default model for every agent, by normalized id from the `models`
#: collection. One default rather than per-agent guesses: nothing here has a
#: measured reason to differ yet, and a fabricated per-agent split would read
#: as a decision somebody made.
DEFAULT_MODEL_ID = "claude-sonnet-4-6-on-vertex"

#: Human labels for stage-id prefixes, so the Studio reads as steps rather than
#: as slugs. Anything unmatched falls back to the id with hyphens removed.
STAGE_LABEL_HINTS: tuple[tuple[str, str], ...] = (
    ("intake", "Intake check"),
    ("load-client-context", "Load client context"),
    ("load-memory-shelf", "Load memory shelf"),
    ("research", "Research pull"),
    ("draft", "Draft"),
    ("copy", "Write copy"),
    ("render", "Render"),
    ("verify", "Verify"),
    ("gate", "Gate"),
    ("review", "Human review"),
    ("deliver", "Deliver"),
    ("persist", "Persist deliverable"),
    ("commit", "Commit and record"),
    ("upload", "Upload"),
)


@dataclass
class Report:
    counts: Counter[str] = field(default_factory=Counter)

    def record(self, outcome: str, what: str) -> None:
        self.counts[outcome] += 1
        symbols = {"created": "+", "updated": "~", "unchanged": "="}
        print(f"  {symbols.get(outcome, '?')} {outcome:<9} {what}")


def humanize(stage_id: str) -> str:
    """A readable label for a step id, without inventing meaning it lacks."""
    body = stage_id.split("-", 1)[1] if "-" in stage_id and stage_id[0].isdigit() else stage_id
    for needle, label in STAGE_LABEL_HINTS:
        if needle in body:
            return label
    return body.replace("-", " ").strip().capitalize() or stage_id


def load_stages() -> dict[str, list[dict[str, Any]]]:
    if not STAGES_FILE.is_file():
        sys.exit(
            f"{STAGES_FILE.name} is missing. Regenerate it from agent-engine's workflow sources "
            "(see this script's docstring) rather than hand-writing a stage list."
        )
    raw = json.loads(STAGES_FILE.read_text(encoding="utf-8"))
    return {
        slug: [
            {
                "id": step["id"],
                "label": humanize(step["id"]),
                "description": None,
                # A gate pauses for a human, which is the difference between an
                # agent that finishes on its own and one that waits.
                "is_gate": step["kind"] == "gate",
            }
            for step in steps
        ]
        for slug, steps in raw.items()
    }


def build_document(entry: dict[str, Any], stages: list[dict[str, Any]], now: Any) -> dict[str, Any]:
    return {
        "id": entry["slug"],
        "slug": entry["slug"],
        "name": entry["name"],
        "description": entry["description"],
        "status": "active",
        "agent_type": entry["agent_type"],
        "model": DEFAULT_MODEL_ID,
        "model_params": {},
        "config": {},
        "tags": entry["tags"],
        "icon": entry["icon"],
        "category": entry["category"],
        "credit_cost": entry["credit_cost"],
        "is_public": True,
        "required_inputs": [
            {
                "key": i["key"],
                "type": i.get("type", "text"),
                "label": i["label"],
                "help_text": i.get("help_text"),
                "required": i.get("required", False),
                "placeholder": i.get("placeholder"),
                "options": i.get("options", []),
            }
            for i in entry["required_inputs"]
        ],
        "stages": stages,
        # These stages are TypeScript. Recorded so the Studio can show what an
        # agent does; editing the list would change a page and not a program.
        "stages_read_only": True,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }


def comparable(row: dict[str, Any]) -> str:
    return json.dumps(
        {k: v for k, v in sorted(row.items()) if k not in {"created_at", "updated_at"}},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--env", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        from google.cloud import firestore  # type: ignore[attr-defined]
    except ImportError:
        sys.exit("google-cloud-firestore is not installed in this environment")

    database = ENVIRONMENTS[args.env]
    db = firestore.Client(project=FIRESTORE_PROJECT, database=database)
    stages_by_slug = load_stages()

    print(f"Registering agent-engine workflows in {FIRESTORE_PROJECT}/{database}")
    print(f"  mode   : {'DRY RUN' if args.dry_run else 'WRITING'}")
    print(f"  agents : {len(CATALOG)}\n")

    report = Report()
    now = firestore.SERVER_TIMESTAMP
    for entry in CATALOG:
        slug = entry["slug"]
        stages = stages_by_slug.get(slug)
        if stages is None:
            # A workflow the extractor did not see is a real mismatch between
            # this catalog and the engine, not something to paper over.
            sys.exit(f"no stages recorded for '{slug}' — regenerate engine_stages.json")

        document = build_document(entry, stages, now)
        label = f"{slug} ({len(stages)} stages, {entry['credit_cost']} credits)"

        if args.dry_run:
            report.record("created", label)
            continue

        ref = db.collection(COLLECTION).document(slug)
        existing = ref.get()
        if existing.exists:
            current = existing.to_dict() or {}
            merged = {**current, **document}
            if comparable({**current, "id": slug}) == comparable(merged):
                report.record("unchanged", label)
                continue
            # merge=True: an agent seeded from the lab repo already has a
            # prompt subcollection and fields this script does not own, and a
            # full overwrite would quietly drop them.
            ref.set(
                {**document, "created_at": current.get("created_at", now), "updated_at": now},
                merge=True,
            )
            report.record("updated", label)
            continue

        ref.set(document)
        report.record("created", label)

    print("\n" + "-" * 60)
    summary = ", ".join(f"{n} {k}" for k, n in sorted(report.counts.items()))
    print("summary: " + (summary or "nothing to do"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

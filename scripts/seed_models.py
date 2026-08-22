#!/usr/bin/env python3
"""Seed the normalized model catalog.

Agent stages used to name a model as free text. This populates the ``models``
collection those stages reference instead, with the Vertex-served models this
platform routes today plus the ones it deliberately does not.

Listing what is NOT enabled is the point of the second group. A catalog showing
only what works reads as "this is everything Vertex has", and someone concludes
a model is unavailable when it is one config change away. Those rows render
disabled in the Studio with a "Request access" action.

``provider_model_name`` is kept separate from the document id because they are
not the same string: Claude served through Vertex is published under a
different name from Claude on Anthropic's own API, and the engine's router
needs the one it will actually send.

Idempotent by content hash, so a re-run writes nothing when unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

ENVIRONMENTS: dict[str, str] = {"prep": "prep", "prod": "(default)"}
FIRESTORE_PROJECT = "karoscmo"
COLLECTION = "models"

#: The catalog. `available` means Vertex offers it AND agent-engine's router
#: is wired for it; `not_enabled` means only the first half is true.
CATALOG: tuple[dict[str, Any], ...] = (
    {
        "model_id": "claude-sonnet-4-6-on-vertex",
        "display_name": "Claude Sonnet 4.6 (Vertex)",
        "vendor": "anthropic",
        "availability": "available",
        "provider_model_name": "claude-sonnet-4-6",
        "region": "global",
        "description": "The default drafting model for every hand-written agent in agent-engine.",
        "context_window": 200_000,
        "supports_tools": True,
        "tiers": ["pinned", "portable"],
    },
    {
        "model_id": "claude-haiku-4-5-on-vertex",
        "display_name": "Claude Haiku 4.5 (Vertex)",
        "vendor": "anthropic",
        "availability": "available",
        "provider_model_name": "claude-haiku-4-5-20251001",
        "region": "global",
        "description": (
            "Classification and gating. What the dynamic runner's topic-guardrail "
            "verifier uses, which is why having guardrails on costs almost nothing."
        ),
        "context_window": 200_000,
        "supports_tools": True,
        "tiers": ["commodity"],
    },
    {
        "model_id": "gemini-2-5-pro",
        "display_name": "Gemini 2.5 Pro",
        "vendor": "google",
        "availability": "available",
        "provider_model_name": "gemini-2.5-pro",
        "region": "us-central1",
        "description": "Long-context reasoning. Wired through the same Vertex router as Claude.",
        "context_window": 1_000_000,
        "supports_tools": True,
        "tiers": ["portable"],
    },
    {
        "model_id": "gemini-2-5-flash",
        "display_name": "Gemini 2.5 Flash",
        "vendor": "google",
        "availability": "available",
        "provider_model_name": "gemini-2.5-flash",
        "region": "us-central1",
        "description": "Cheap, fast extraction and classification.",
        "context_window": 1_000_000,
        "supports_tools": True,
        "tiers": ["commodity"],
    },
    {
        "model_id": "claude-opus-4-8-on-vertex",
        "display_name": "Claude Opus 4.8 (Vertex)",
        "vendor": "anthropic",
        "availability": "not_enabled",
        "provider_model_name": "claude-opus-4-8",
        "region": "global",
        "description": "Highest-capability Anthropic tier.",
        "context_window": 200_000,
        "supports_tools": True,
        "tiers": ["pinned"],
        "notes": (
            "Not routed here: no agent currently justifies the per-run cost. Ask via the "
            "Studio's Request access action if a stage genuinely needs it."
        ),
    },
    {
        "model_id": "llama-3-1-70b-instruct-maas",
        "display_name": "Llama 3.1 70B Instruct (MaaS)",
        "vendor": "meta",
        "availability": "not_enabled",
        "provider_model_name": "meta/llama-3.1-70b-instruct-maas",
        "region": "us-central1",
        "description": "Open-weights option served through Vertex Model-as-a-Service.",
        "context_window": 128_000,
        "supports_tools": False,
        "tiers": ["commodity"],
        "notes": (
            "Not routed here, and note supports_tools is false: any stage granting tools "
            "would not work on it even once enabled."
        ),
    },
)


@dataclass
class Report:
    counts: Counter[str] = field(default_factory=Counter)

    def record(self, outcome: str, what: str) -> None:
        self.counts[outcome] += 1
        symbols = {"created": "+", "updated": "~", "unchanged": "="}
        print(f"  {symbols.get(outcome, '?')} {outcome:<9} {what}")


def _comparable(row: dict[str, Any]) -> str:
    """Everything except the timestamps, so an unchanged row is recognised as one."""
    return json.dumps(
        {k: v for k, v in sorted(row.items()) if k not in {"created_at", "updated_at"}},
        ensure_ascii=False,
        sort_keys=True,
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

    print(f"Seeding the model catalog into {FIRESTORE_PROJECT}/{database}")
    print(f"  mode : {'DRY RUN' if args.dry_run else 'WRITING'}")
    print(f"  rows : {len(CATALOG)}\n")

    report = Report()
    now = firestore.SERVER_TIMESTAMP
    for entry in CATALOG:
        document = {"id": entry["model_id"], **entry}
        document.setdefault("notes", None)
        document.setdefault("description", None)
        label = f"{entry['model_id']} ({entry['availability']})"

        if args.dry_run:
            report.record("created", label)
            continue

        ref = db.collection(COLLECTION).document(entry["model_id"])
        existing = ref.get()
        if existing.exists:
            current = existing.to_dict() or {}
            if _comparable({**current, "id": entry["model_id"]}) == _comparable(document):
                report.record("unchanged", label)
                continue
            ref.set({**document, "updated_at": now}, merge=True)
            report.record("updated", label)
            continue

        ref.set({**document, "created_at": now, "updated_at": now})
        report.record("created", label)

    print("\n" + "-" * 60)
    summary = ", ".join(f"{n} {k}" for k, n in sorted(report.counts.items()))
    print("summary: " + (summary or "nothing to do"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

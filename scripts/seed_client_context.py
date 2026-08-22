#!/usr/bin/env python3
"""Project karosCMO's client records into the agent-engine workspace store.

agent-engine reads a client's onboarding data through the ``client.*`` tools,
which read one JSON record per key out of the workspace bucket::

    gs://<bucket>/clients/<slug>/client/profile.json
    gs://<bucket>/clients/<slug>/client/brand.json
    gs://<bucket>/clients/<slug>/client/voice-rules.json
    gs://<bucket>/clients/<slug>/client/config.json

Production had none of these, so every production agent-engine run would stop
at ``blocked_intake`` before doing any work. This projects them from the two
places the data actually lives:

* **karosCMO Firestore** (``clients`` collection) -- the authoritative record
  a human edits in the portal: name, industry, website, branding guidelines,
  brand voice. Source for profile / brand / voice-rules.
* **an existing environment's ``config.json``** (``--carry-config-from``) --
  engine-specific settings that are not portal fields and cannot be derived
  from one: an X handle, a client's frozen Instagram style config. Carried
  forward rather than regenerated.

Nothing is invented. A client whose record has no industry gets no
``industry`` key, not a guess. In particular this does NOT synthesise
``instagramStyleConfig``/``instagramBrandTokens``: instagram-agent refuses to
guess those and blocks the run instead, and a seeder that quietly invented
them would defeat exactly the check that exists to stop unreviewed styling
reaching a client's feed.

Idempotent by content hash, so re-running writes nothing when unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

ENVIRONMENTS: dict[str, dict[str, str]] = {
    "prep": {"bucket": "karoscmo-prep-agent-artifacts", "database": "prep"},
    "prod": {"bucket": "karoscmo-prod-agent-artifacts", "database": "(default)"},
}

FIRESTORE_PROJECT = "karoscmo"

#: Slugs that are test fixtures, never real clients. Copying these into a real
#: environment is how synthetic data ends up in a production listing.
TEST_SLUGS = {"acme", "acme2", "acme3", "acme4", "acme-corp", "test", "demo"}


@dataclass
class Report:
    counts: Counter[str] = field(default_factory=Counter)

    def record(self, outcome: str, what: str) -> None:
        self.counts[outcome] += 1
        symbols = {"created": "+", "updated": "~", "unchanged": "=", "skipped": "-"}
        print(f"  {symbols.get(outcome, '?')} {outcome:<9} {what}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(mapping: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values so an absent field stays absent rather than becoming ''."""
    return {k: v for k, v in mapping.items() if v not in (None, "", [], {})}


def build_profile(doc: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "name": doc.get("name"),
            "slug": doc.get("agentsRepoSlug"),
            "industry": doc.get("industry"),
            "description": doc.get("description"),
            "website": doc.get("website"),
            "domains": doc.get("domains"),
        }
    )


def build_brand(doc: dict[str, Any]) -> dict[str, Any]:
    guidelines = doc.get("brandingGuidelines") or {}
    colors = _clean(
        {
            "primaryAccent": guidelines.get("primaryAccent") or doc.get("accentColor"),
            "secondaryAccent": guidelines.get("secondaryAccent"),
            "neutralDark": guidelines.get("brandNeutralDark"),
            "neutralLight": guidelines.get("brandNeutralLight"),
        }
    )
    return _clean(
        {
            "name": doc.get("name"),
            "accent": guidelines.get("primaryAccent") or doc.get("accentColor"),
            "colors": colors,
            "dominantColors": guidelines.get("dominantColors"),
            "fonts": _clean(
                {"heading": guidelines.get("fontHeading"), "body": guidelines.get("fontBody")}
            ),
            "visualStyle": guidelines.get("visualStyle"),
            "guidelines": guidelines.get("guidelines"),
            "logoUrl": guidelines.get("logoUrl") or doc.get("logoUrl"),
        }
    )


def build_voice_rules(doc: dict[str, Any]) -> dict[str, Any]:
    guidelines = doc.get("brandingGuidelines") or {}
    tone_keywords = guidelines.get("toneKeywords") or []
    return _clean(
        {
            # brandVoice is the portal's own free-text voice field; the tone
            # keywords are the structured half. Both are the client's words.
            "tone": doc.get("brandVoice") or (", ".join(tone_keywords) if tone_keywords else None),
            "toneKeywords": tone_keywords,
            # Deliberately not populated from anything: forbiddenTerms is a
            # real editorial gate and there is no portal field for it yet.
            # An empty list here would read as "nothing is forbidden".
            "guidelines": guidelines.get("guidelines"),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--env", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument(
        "--carry-config-from",
        choices=sorted(ENVIRONMENTS),
        help=(
            "Copy each client's existing client/config.json from this "
            "environment when the target has none"
        ),
    )
    parser.add_argument("--only", help="Restrict to one client slug")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = ENVIRONMENTS[args.env]
    try:
        # Namespace packages; same note as seed_legacy_agents.py.
        from google.cloud import firestore, storage  # type: ignore[attr-defined]
    except ImportError:
        sys.exit("google-cloud-firestore and google-cloud-storage must be installed")

    db = firestore.Client(project=FIRESTORE_PROJECT, database=target["database"])
    storage_client = storage.Client()
    bucket = storage_client.bucket(target["bucket"])
    source_bucket = (
        storage_client.bucket(ENVIRONMENTS[args.carry_config_from]["bucket"])
        if args.carry_config_from
        else None
    )

    print(f"Projecting client context into gs://{target['bucket']}/clients/<slug>/client/")
    print(f"  source   : firestore {FIRESTORE_PROJECT}/{target['database']} (clients)")
    if args.carry_config_from:
        print(f"  config   : carried from {args.carry_config_from} when absent here")
    print(f"  mode     : {'DRY RUN' if args.dry_run else 'WRITING'}\n")

    report = Report()
    for snapshot in db.collection("clients").stream():
        doc = snapshot.to_dict() or {}
        slug = doc.get("agentsRepoSlug")
        if not slug:
            report.record("skipped", f"{doc.get('name') or snapshot.id} (no agentsRepoSlug)")
            continue
        if slug in TEST_SLUGS:
            report.record("skipped", f"{slug} (test fixture)")
            continue
        if args.only and slug != args.only:
            continue

        print(f"{slug}  ({doc.get('name')})")
        records: dict[str, dict[str, Any]] = {
            "profile": build_profile(doc),
            "brand": build_brand(doc),
            "voice-rules": build_voice_rules(doc),
        }

        # config.json is engine-specific and not derivable from a portal
        # field, so it is only ever carried forward, never generated.
        if source_bucket is not None:
            src = source_bucket.blob(f"clients/{slug}/client/config.json")
            if src.exists():
                records["config"] = json.loads(src.download_as_text())

        for key, payload in records.items():
            if not payload:
                report.record("skipped", f"{key} (no data in the client record)")
                continue
            body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            path = f"clients/{slug}/client/{key}.json"
            if args.dry_run:
                report.record("created", f"{key} ({len(payload)} fields) -> {path}")
                continue
            blob = bucket.blob(path)
            if blob.exists():
                if _sha(blob.download_as_text()) == _sha(body):
                    report.record("unchanged", key)
                    continue
                outcome = "updated"
            else:
                outcome = "created"
            blob.upload_from_string(body, content_type="application/json")
            report.record(outcome, f"{key} ({len(payload)} fields)")

    print("\n" + "-" * 60)
    summary = ", ".join(f"{n} {k}" for k, n in sorted(report.counts.items()))
    print("summary: " + (summary or "nothing to do"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

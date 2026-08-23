#!/usr/bin/env python3
"""Seed the editorial half of a client's workspace, and only that half.

## The line this script draws

``report_client_readiness.py`` splits a client's gaps into two kinds, and the
split is the whole design of this script:

* **Identity and rights** -- which X account posts, which subreddits get
  replied to, which Instagram styling was approved, which shows the client
  holds the rights to clip. Nothing in the portal holds these, so seeding them
  means inventing them, and a wrong one does not fail safe: an agent holding a
  guessed handle *succeeds*, and hands a reviewer finished drafts aimed at
  somebody else's account. **This script refuses to write any of them** and
  lists them instead.

* **Editorial** -- what this client is worth writing about. Derived from their
  real portal record (industry, description, website, brand voice), stamped
  with where each value came from, and reviewed by a human at the approval
  gate every agent already has before anything ships. A weak topic is a
  quality problem that the review catches. A wrong handle is not.

The test to apply when adding a field here: if this value is wrong, does the
agent take an action against an outside party that nobody verified, or does it
just produce something mediocre that a reviewer will reject? Only the second
kind belongs in this script.

## Provenance

Everything written carries ``_derivedFrom``, naming the portal fields it came
from, and ``_derivedAt``. That is what stops a derived content pillar being
mistaken later for an editorial plan somebody actually made -- and it is what
lets a future run of this script tell its own output apart from a human's.
Values a human has edited (no ``_derivedFrom``) are never overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

ENVIRONMENTS: dict[str, dict[str, str]] = {
    "prep": {"bucket": "karoscmo-prep-agent-artifacts", "database": "prep"},
    "prod": {"bucket": "karoscmo-prod-agent-artifacts", "database": "(default)"},
}

#: Keys this script will never write, with the reason. Checked rather than
#: merely documented: a later edit that adds one of these to the derivation
#: below trips the assertion instead of shipping.
FORBIDDEN_KEYS: dict[str, str] = {
    "xHandle": "an X account nobody verified belongs to this client",
    "targetSubreddits": (
        "communities nobody vetted, on a product where a human posts the reply "
        "from their own account"
    ),
    "instagramStyleConfig": (
        "unreviewed styling reaching a client's feed -- instagram-agent refuses "
        "to guess it for this reason"
    ),
    "instagramBrandTokens": "same as instagramStyleConfig",
    "brandedShortsProfilePath": (
        "a locked brand style that only the Style Exploration onboarding produces"
    ),
    "brandedShortsGraphicsLanguage": "same as brandedShortsProfilePath",
    "brandedShortsApprovedArchetypes": "an approved repertoire, not a default",
    "tiktokClips": "which shows a client holds the rights to clip",
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "their",
    "from",
    "your",
    "you",
    "are",
    "was",
    "were",
    "who",
    "what",
    "into",
    "they",
    "them",
    "its",
    "it's",
    "our",
    "not",
    "but",
    "all",
    "can",
    "has",
    "have",
    "had",
    "will",
    "would",
    "more",
    "most",
    "than",
    "then",
    "when",
    "where",
    "how",
    "why",
    "about",
    "over",
    "under",
    "just",
    "like",
    "also",
    "very",
    "much",
    "some",
    "any",
}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text or "")]


def keywords_from(record: dict[str, Any], limit: int = 8) -> list[str]:
    """Distinctive words from the client's own description and industry.

    Frequency-ranked over their real prose, not a restatement of the industry
    field. Deliberately simple and deterministic: the value of this list is
    that it is demonstrably derived from what the client says about
    themselves, and a cleverer extraction would be harder to audit for exactly
    the property that matters.
    """
    text = " ".join(
        str(record.get(k) or "")
        for k in ("description", "industry", "brandVoice", "brandingGuidelines")
    )
    counts: dict[str, int] = {}
    for word in _words(text):
        key = word.lower()
        if key in STOPWORDS:
            continue
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _ in ranked[:limit]]


def pillars_from(record: dict[str, Any]) -> list[str]:
    """Content pillars, as sentences from the client's own description.

    Their sentences, not a paraphrase. A pillar that reads as something the
    client actually said about themselves is one a human can confirm or reject
    at a glance; a generated summary of it is one they have to go and check.
    """
    description = str(record.get("description") or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", description) if len(s.strip()) > 20]
    if sentences:
        return sentences[:3]
    industry = str(record.get("industry") or "").strip()
    return [industry] if industry else []


# NO TOPIC CATALOG IS GENERATED HERE, and the reason is worth recording.
#
# The first version of this script templated one: it crossed the client's
# keywords with angle phrases ("What changed recently in {subject}") to fill
# the catalog to the lane floor of 5. Against real production data that
# produced rows like "What changed recently in every" and "What changed
# recently in application" -- because a one-line company description does not
# contain five distinct subjects, and padding it to five invents the
# difference.
#
# That is the identity failure again in a milder key. A templated catalog does
# not fail loudly; it UNBLOCKS the agents and they draft against it, and the
# result is plausible-looking work about nothing, produced at cost, for a
# human to reject one draft at a time.
#
# It is also unnecessary for five of the seven channel agents. x, linkedin,
# reddit, blog and newsletter each treat an empty catalog as a soft miss and
# fall through to a research-derived candidate -- real research against the
# live web beats a string template on any reading. Only instagram-agent and
# tiktok-agent stop hard, and what they need is a curated set of subjects
# somebody chose, which is a research or editorial task rather than a seeding
# one.


def editorial_config(record: dict[str, Any]) -> dict[str, Any]:
    """The config keys blog-agent and newsletter-agent block on."""
    pillars = pillars_from(record)
    keywords = keywords_from(record)
    industry = str(record.get("industry") or "").strip()
    out: dict[str, Any] = {}
    if pillars:
        out["contentPillars"] = pillars
    if keywords:
        out["targetKeywords"] = keywords
    if industry:
        # An audience statement derived from the industry, and labelled as
        # such. Weak, and honestly so -- it exists to let newsletter-agent
        # start, and a reviewer replacing it is the expected path.
        out["targetAudience"] = f"Readers and buyers in {industry}"
    out["frequency"] = "weekly"
    for key in out:
        assert key not in FORBIDDEN_KEYS, (
            f"{key} is on the forbidden list and must never be derived"
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--env", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument("--client", action="append", help="Restrict to one slug; repeatable.")
    parser.add_argument(
        "--confirm", action="store_true", help="Required to write. Without it this is a dry run."
    )
    parser.add_argument(
        "--timestamp", required=True, help="Recorded as _derivedAt, e.g. 2026-08-23T20:00Z"
    )
    args = parser.parse_args()

    try:
        from google.cloud import firestore, storage  # type: ignore[attr-defined]
    except ImportError:
        sys.exit("google-cloud-firestore and google-cloud-storage must be installed")

    env = ENVIRONMENTS[args.env]
    db = firestore.Client(project="karoscmo", database=env["database"])
    bucket = storage.Client().bucket(env["bucket"])

    # `to_dict()` is Optional on a snapshot that vanished mid-stream. Read once
    # and skip the empty ones rather than calling it twice and trusting both.
    records: dict[str, dict[str, Any]] = {}
    for snapshot in db.collection("clients").stream():
        record = snapshot.to_dict()
        if not record:
            continue
        records[str(record.get("agentsRepoSlug") or "")] = record
    slugs = args.client or sorted(s for s in records if s)

    print(f"Editorial seeding — {args.env} (gs://{env['bucket']})")
    print(f"  mode: {'WRITING' if args.confirm else 'DRY RUN'}\n")

    for slug in slugs:
        record = records.get(slug)
        if record is None:
            print(f"  {slug}: no portal record — skipped")
            continue

        derived = editorial_config(record)
        provenance = {
            "_derivedFrom": sorted(
                k
                for k in ("description", "industry", "brandVoice", "brandingGuidelines")
                if record.get(k)
            ),
            "_derivedAt": args.timestamp,
        }
        config_blob = bucket.blob(f"clients/{slug}/client/config.json")
        existing: dict[str, Any] = {}
        if config_blob.exists():
            try:
                existing = json.loads(config_blob.download_as_text())
            except ValueError:
                existing = {}
        if existing.get("_placeholder"):
            print(f"  {slug}: config is a prep placeholder — refusing to build on it")
            continue

        # Never overwrite a value a human set. A key that is present without
        # our provenance stamp was put there by somebody who meant it.
        human_owned = [k for k in derived if k in existing and "_derivedFrom" not in existing]
        writable = {k: v for k, v in derived.items() if k not in human_owned}

        print(f"  {slug}")
        print(
            f"    config keys : {sorted(writable) or 'none'}"
            + (f"  (kept human-set: {human_owned})" if human_owned else "")
        )
        still_blocked = sorted(FORBIDDEN_KEYS)
        print(f"    STILL NEEDS A PERSON: {', '.join(still_blocked)}")

        if not args.confirm:
            continue

        if writable:
            config_blob.upload_from_string(
                json.dumps({**existing, **writable, **provenance}, indent=2, ensure_ascii=False),
                content_type="application/json",
            )

    print("\n" + "-" * 72)
    if args.confirm:
        print("done — re-run report_client_readiness.py to see the new picture")
    else:
        print("dry run — nothing written. Pass --confirm to act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

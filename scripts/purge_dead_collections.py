#!/usr/bin/env python3
"""Archive and delete Firestore collections nothing reads any more.

## Why this has an allow-list and not a pattern

The obvious version of this script takes "everything except the canonical
collections" and deletes it. That is how you lose a portal. Prep has 50 root
collections; a plausible-looking canonical list of seven omits ``assets``,
``jobs``, ``users``, ``creditLedger``, ``transcripts`` and thirty-eight others
that are all live. So this script deletes exactly what is named below and
refuses anything else, and each name is here because it was checked.

## How each name was established as dead

Grepped for across all three repositories -- karosCMO's ``src/``,
agent-engine's ``packages/`` and ``apps/``, agent-middleware's ``app/`` --
excluding tests and build output. Zero references, in any of them.

That check is what rules names IN as well as out. ``liAgentState`` and
``carouselAgentState`` look dead and are not: karosCMO still reads both.
``agentDefinitions`` is agent-engine's dynamic-agent store and ``agent_runs``
is this service's own runs collection; neither appears in karosCMO, which is
exactly why a single-repo grep would have condemned them.

## Archive first

Every document is written to
``gs://<bucket>/archive/dead-collections/<timestamp>/<collection>.json``
before anything is deleted. These are small (seven documents in prep) and the
cost of keeping them is nil against the cost of being wrong about one.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

ENVIRONMENTS: dict[str, dict[str, str]] = {
    "prep": {"database": "prep", "bucket": "karoscmo-prep-agent-artifacts"},
    "prod": {"database": "(default)", "bucket": "karoscmo-prod-agent-artifacts"},
}
FIRESTORE_PROJECT = "karoscmo"


@dataclass(frozen=True)
class DeadCollection:
    name: str
    reason: str


#: The only collections this script may touch. Anything absent is refused.
DEAD_COLLECTIONS: tuple[DeadCollection, ...] = (
    DeadCollection(
        "contentEngineConfigs",
        "content-engine e12, removed from karosCMO 2026-07; no reference in any repo",
    ),
    DeadCollection(
        "contentCatalogs",
        "content-engine e12's catalog; removed with it",
    ),
    DeadCollection(
        "contentLedger",
        "content-engine e12's ledger; removed with it",
    ),
    DeadCollection(
        "newsletterConfigs",
        "newsletter e11, retired 2026-08-06 when the product moved to the v2 custom agent",
    ),
    DeadCollection(
        "_importPreflight",
        "scratch health-check rows written by an importer preflight that no longer runs",
    ),
)

DEAD_BY_NAME = {c.name: c for c in DEAD_COLLECTIONS}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--env", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument(
        "--only",
        action="append",
        help="Restrict to one named collection; repeatable. Must still be on the allow-list.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be archived and deleted, and touch nothing.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to actually delete. Without it this is a dry run whatever else is passed.",
    )
    parser.add_argument(
        "--timestamp", required=True, help="Archive folder name, e.g. 2026-08-23T1400Z"
    )
    args = parser.parse_args()

    targets = list(DEAD_COLLECTIONS)
    if args.only:
        unknown = [name for name in args.only if name not in DEAD_BY_NAME]
        if unknown:
            sys.exit(
                f"refusing: {', '.join(unknown)} is not on the allow-list. Add it to "
                "DEAD_COLLECTIONS with the evidence that nothing reads it, or do not delete it."
            )
        targets = [DEAD_BY_NAME[name] for name in args.only]

    # `--dry-run` and "no --confirm" are the same thing on purpose: the safe
    # mode has to be what you get by forgetting a flag, not by remembering one.
    writing = args.confirm and not args.dry_run

    try:
        from google.cloud import firestore, storage  # type: ignore[attr-defined]
    except ImportError:
        sys.exit("google-cloud-firestore and google-cloud-storage must be installed")

    env = ENVIRONMENTS[args.env]
    db = firestore.Client(project=FIRESTORE_PROJECT, database=env["database"])
    bucket = storage.Client().bucket(env["bucket"])
    prefix = f"archive/dead-collections/{args.timestamp}"

    print(f"Purging dead collections from {FIRESTORE_PROJECT}/{env['database']}")
    print(f"  mode    : {'DELETING' if writing else 'DRY RUN'}")
    print(f"  archive : gs://{env['bucket']}/{prefix}/\n")

    archived = 0
    deleted = 0
    for target in targets:
        docs = list(db.collection(target.name).stream())
        if not docs:
            print(f"  = {target.name}: already empty")
            continue

        payload: list[dict[str, Any]] = [
            {"id": d.id, "data": json.loads(json.dumps(d.to_dict() or {}, default=str))}
            for d in docs
        ]
        print(f"  - {target.name}: {len(docs)} doc(s) — {target.reason}")

        if not writing:
            continue

        # Archive before deleting, and verify the write landed: an archive that
        # silently failed turns this into a plain delete.
        blob = bucket.blob(f"{prefix}/{target.name}.json")
        blob.upload_from_string(
            json.dumps(payload, ensure_ascii=False, indent=2), content_type="application/json"
        )
        if not blob.exists():
            sys.exit(f"archive for {target.name} did not land; refusing to delete")
        archived += len(payload)

        for d in docs:
            d.reference.delete()
            deleted += 1

    print("\n" + "-" * 60)
    if writing:
        print(f"archived {archived} document(s), deleted {deleted}")
    else:
        print("dry run — nothing archived, nothing deleted. Pass --confirm to act.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

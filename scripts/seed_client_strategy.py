#!/usr/bin/env python3
"""Migrate per-client agent setup documents from the karos-agents lab repo.

The lab repo carries a filled-in intake form per client, per agent, and for
``x-agent``/``linkedin-agent`` per *account or seat*::

    clients/<slug>/internal/x-agent/account-intake/<account>.md
    clients/<slug>/internal/linkedin-agent/seat-intake/<person>.md
    clients/<slug>/internal/linkedin-agent/company-updates.md
    clients/<slug>/internal/reddit-agent/voice/<account>.md

These say what an account is chartered to be known for and what it must never
post. ``client.getProfile``/``getBrand``/``getVoiceRules`` describe how a
client *sounds*; none of them carry a charter, so until now a run could not
see one.

Destination is the agent-engine workspace store, which is GCS::

    gs://<bucket>/clients/<slug>/strategy/<agent>.json
    gs://<bucket>/clients/<slug>/strategy/<agent>/<key>.json

GCS and not Firestore, deliberately. That bucket and prefix are already the
workspace store's own layout, so every ``client.*`` tool reads it today with
no new client, no new credential and no new failure mode --
``client.getStrategy`` is a short reader over the existing store. These are
also whole documents, only ever read entire and never queried by field, and
several run past what a Firestore document comfortably holds.

The ``{"markdown": ...}`` envelope matches ``landing/intake.json``, which
already carries the landing bundle's ``intake.md`` the same way.

Idempotent by content hash: a re-run writes nothing when the document is
unchanged, so this is safe to repeat and safe to resume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Same presets as seed_legacy_agents.py -- one source of truth for what prod is.
ENVIRONMENTS: dict[str, str] = {
    "prep": "karoscmo-prep-agent-artifacts",
    "prod": "karoscmo-prod-agent-artifacts",
}

#: Where each agent's documents live in the lab repo. ``subdir`` set means
#: every .md in that directory becomes a keyed document; ``single`` set means
#: that one file is the agent's account-level document.
LAYOUT: tuple[tuple[str, str | None, str | None], ...] = (
    # (agent, subdirectory under internal/<agent>/, single-file name)
    ("x-agent", "account-intake", None),
    ("linkedin-agent", "seat-intake", None),
    ("linkedin-agent", None, "company-updates.md"),
    ("reddit-agent", "voice", None),
    ("reddit-agent", None, "AGENT-MEMORY.md"),
)

#: Project documentation, not a client's charter. Migrating these would hand a
#: model a build brief as though it were standing direction.
SKIP_NAMES = {
    "README.md",
    "PORTAL-BUILDOUT-BRIEF.md",
    "PORTAL-HANDOFF.md",
    "QUESTIONNAIRE-FOR-YAIR.md",
}


@dataclass
class Report:
    counts: Counter[str] = field(default_factory=Counter)

    def record(self, outcome: str, what: str) -> None:
        self.counts[outcome] += 1
        symbols = {"created": "+", "updated": "~", "unchanged": "=", "skipped": "-"}
        symbol = symbols.get(outcome, "?")
        print(f"  {symbol} {outcome:<9} {what}")


def slugify(name: str) -> str:
    """Match the lab repo's own kebab-cased filenames, which become the keys."""
    lowered = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return lowered.strip("-")


@dataclass
class Doc:
    client: str
    agent: str
    key: str | None
    markdown: str
    source_path: str

    def object_path(self) -> str:
        tail = f"{self.agent}/{self.key}" if self.key else self.agent
        return f"clients/{self.client}/strategy/{tail}.json"

    def payload(self) -> dict[str, Any]:
        return {
            "markdown": self.markdown,
            # Provenance travels with the document: months from now, "why does
            # this account refuse to mention pricing" is answerable by opening
            # the file it came from.
            "source": {"repo": "karos-agents", "path": self.source_path},
        }


def collect(lab_root: Path) -> list[Doc]:
    docs: list[Doc] = []
    clients_dir = lab_root / "clients"
    if not clients_dir.is_dir():
        sys.exit(f"no clients/ directory under {lab_root} -- is this a karos-agents checkout?")

    for client_dir in sorted(p for p in clients_dir.iterdir() if p.is_dir()):
        client = client_dir.name
        if client.startswith("_"):
            continue  # _cso and friends are internal scaffolding, not a client
        for agent, subdir, single in LAYOUT:
            base = client_dir / "internal" / agent
            if single is not None:
                path = base / single
                if path.is_file() and path.name not in SKIP_NAMES:
                    docs.append(
                        Doc(
                            client,
                            agent,
                            None,
                            path.read_text(encoding="utf-8"),
                            _rel(path, lab_root),
                        )
                    )
                continue
            folder = base / subdir if subdir else base
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.md")):
                if path.name in SKIP_NAMES:
                    continue
                docs.append(
                    Doc(
                        client,
                        agent,
                        slugify(path.stem),
                        path.read_text(encoding="utf-8"),
                        _rel(path, lab_root),
                    )
                )
    return docs


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--karos-agents", default="../karos-agents", help="Path to a karos-agents checkout"
    )
    parser.add_argument("--env", choices=sorted(ENVIRONMENTS), required=True)
    parser.add_argument("--bucket", help="Override the destination bucket")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change, write nothing"
    )
    args = parser.parse_args()

    lab_root = Path(args.karos_agents).resolve()
    bucket_name = args.bucket or ENVIRONMENTS[args.env]
    docs = collect(lab_root)

    print(f"Migrating client strategy docs from {lab_root}")
    print(f"  target : gs://{bucket_name}/clients/<slug>/strategy/")
    print(f"  mode   : {'DRY RUN' if args.dry_run else 'WRITING'}")
    print(f"  found  : {len(docs)} document(s)\n")

    bucket = None
    if not args.dry_run:
        try:
            # Namespace package; same note as seed_legacy_agents.py.
            from google.cloud import storage  # type: ignore[attr-defined]
        except ImportError:
            sys.exit("google-cloud-storage is not installed in this environment")
        # Fail before the first write, never partway through: a dependency or
        # permission problem found on document 9 of 17 leaves a half-migrated
        # client, which is worse than not starting.
        bucket = storage.Client().bucket(bucket_name)
        if not bucket.exists():
            sys.exit(f"bucket gs://{bucket_name} is not reachable")

    report = Report()
    current_client = None
    for doc in docs:
        if doc.client != current_client:
            current_client = doc.client
            print(f"{doc.client}")
        label = f"{doc.agent}{'/' + doc.key if doc.key else ''} ({len(doc.markdown)} chars)"
        body = json.dumps(doc.payload(), ensure_ascii=False, indent=2)

        if args.dry_run:
            report.record("created", f"{label} -> {doc.object_path()}")
            continue

        assert bucket is not None
        blob = bucket.blob(doc.object_path())
        if blob.exists():
            existing = blob.download_as_bytes()
            if hashlib.sha256(existing).hexdigest() == _sha(body):
                report.record("unchanged", label)
                continue
            outcome = "updated"
        else:
            outcome = "created"
        blob.upload_from_string(body, content_type="application/json")
        report.record(outcome, label)

    print("\n" + "-" * 60)
    summary = ", ".join(f"{n} {k}" for k, n in sorted(report.counts.items()))
    print("summary: " + (summary or "nothing to do"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

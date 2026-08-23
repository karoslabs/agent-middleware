"""The client-context projection script, and specifically its topic catalog.

The pure builders are what is worth testing here: the script's I/O half is two
GCS blob writes guarded by an ``exists()`` check, while the ``--skeleton``
payloads are where a mistake reaches an agent as either a blocked run or, worse,
invented client data.

THE PROPERTY THAT ACTUALLY MATTERS is that the seeded topic catalog can serve a
reservation. ``topics.reserve`` in agent-engine refuses any reservation that
would leave a lane below ``LANE_FLOOR`` (5), so a catalog of five rows is
indistinguishable in effect from no catalog at all — and no catalog at all is
the state prep was actually in: nothing in either repo writes that file, so
every ``topics.reserve`` call breached the floor forever, which killed every
instagram-agent run at step 03.
"""

from __future__ import annotations

from typing import Any

from scripts.seed_client_context import (
    TOPIC_DEFAULT_LANE,
    TOPIC_LANE_FLOOR,
    TOPIC_SUBJECT_TEMPLATES,
    build_profile,
    skeleton_extras,
    skeleton_topics_catalog,
)

CLIENT: dict[str, Any] = {
    "name": "Geektime",
    "agentsRepoSlug": "geektime",
    "industry": "B2B SaaS",
    "brandingGuidelines": {"primaryAccent": "#123456"},
}


class TestTopicCatalog:
    def test_seeds_more_rows_than_the_lane_floor_so_a_reservation_can_succeed(self) -> None:
        rows = skeleton_topics_catalog(CLIENT, "geektime")
        # Strictly greater, not >=: `topics.reserve` compares
        # `available - count < LANE_FLOOR`, so exactly FLOOR rows still breaches.
        assert len(rows) > TOPIC_LANE_FLOOR
        # Two weeks of daily cadence on top of the floor is what
        # carousel-agent-v2's SKILL.md step 04 asks a seeded lane to hold.
        assert len(rows) - TOPIC_LANE_FLOOR >= 14

    def test_every_row_matches_the_engine_TopicRecord_shape(self) -> None:
        for row in skeleton_topics_catalog(CLIENT, "geektime"):
            # The four fields `karos-topics` actually reads. `reservationKey` is
            # written by the tool itself on reserve, never seeded.
            assert set(row) == {"_placeholder", "topic", "normalized", "status", "lane"}
            assert row["status"] == "available"
            assert row["lane"] == TOPIC_DEFAULT_LANE
            assert row["topic"].strip() == row["topic"]
            # `normalizeTopic` in the engine is `trim().toLowerCase()`.
            assert row["normalized"] == row["topic"].strip().lower()

    def test_rows_are_distinct_after_substitution(self) -> None:
        # `topics.reserve` dedups on `normalized`, so two templates collapsing
        # onto one string would seed a row that can never be reserved separately.
        rows = skeleton_topics_catalog(CLIENT, "geektime")
        assert len({r["normalized"] for r in rows}) == len(rows)

    def test_lands_in_the_lane_instagram_agent_actually_asks_for(self) -> None:
        # instagram-agent is the only caller that passes a lane, and it defaults
        # to DEFAULT_CAROUSEL_LANE. Seeding any other lane leaves it breaching.
        assert TOPIC_DEFAULT_LANE == "general"
        assert {r["lane"] for r in skeleton_topics_catalog(CLIENT, "geektime")} == {"general"}

    def test_marks_every_row_as_a_placeholder(self) -> None:
        # The catalog is a JSON array with no envelope to hang one marker on, so
        # the marker rides on each row. Anyone opening the file must be able to
        # tell nobody chose these.
        assert all(r["_placeholder"] is True for r in skeleton_topics_catalog(CLIENT, "geektime"))

    def test_subjects_are_prompts_rather_than_claims(self) -> None:
        # The line that makes this seedable at all: a subject to write about
        # asserts nothing, so the drafting agent still has to research and source
        # it. A seeded statistic or milestone would be fabricated client data.
        for template in TOPIC_SUBJECT_TEMPLATES:
            assert "%" not in template
            assert not any(ch.isdigit() for ch in template)

    def test_degrades_to_a_neutral_subject_when_the_client_declares_no_industry(self) -> None:
        rows = skeleton_topics_catalog({}, "someclient")
        assert len(rows) > TOPIC_LANE_FLOOR
        assert all("{industry}" not in r["topic"] for r in rows)

    def test_uses_the_client_s_own_industry_when_there_is_one(self) -> None:
        rows = skeleton_topics_catalog(CLIENT, "geektime")
        assert any("B2B SaaS" in r["topic"] for r in rows)


class TestSkeletonExtras:
    def test_writes_the_catalog_to_the_path_the_engine_reads(self) -> None:
        # `CATALOG_SEGMENTS = ["topics", "catalog"]` under the store's
        # `clients/<slug>/` prefix, plus `.json`.
        path, payload = skeleton_extras(CLIENT, "geektime")["topics/catalog"]
        assert path == "clients/geektime/topics/catalog.json"
        assert isinstance(payload, list)

    def test_still_carries_the_three_per_agent_extras(self) -> None:
        # The catalog is additive; nothing it replaced should have gone away.
        assert set(skeleton_extras(CLIENT, "geektime")) == {
            "landing/brand",
            "landing/intake",
            "memory/beliefs",
            "topics/catalog",
        }


class TestProfileProjection:
    def test_industry_reaches_the_profile_the_fallback_reads(self) -> None:
        # instagram-agent's new step-03 fallback derives its subject from
        # `client/profile.json`'s `industry`, so a client whose portal record has
        # one must end up with that key here — otherwise the fallback's last rung
        # is unreachable and the run holds.
        assert build_profile(CLIENT)["industry"] == "B2B SaaS"

    def test_an_absent_industry_stays_absent_rather_than_becoming_a_guess(self) -> None:
        assert "industry" not in build_profile({"name": "Nameless", "agentsRepoSlug": "n"})

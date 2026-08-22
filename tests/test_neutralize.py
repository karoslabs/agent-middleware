"""The harness-vocabulary rewrites.

Each test pins *meaning preservation*, not just that the detector goes quiet.
A rule that satisfied `find_claude_isms` by mangling an instruction would be
worse than leaving the Claude-ism in place, because the failure would be
silent — so the assertions here check that the surviving sentence still says
the thing the original said.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.legacy_manifest import AGENT_SPECS
from scripts.neutralize import RULES, neutralize
from scripts.seed_legacy_agents import compose_prompt, find_claude_isms

KAROS_AGENTS = Path(__file__).resolve().parent.parent.parent / "karos-agents"
needs_lab_repo = pytest.mark.skipif(
    not KAROS_AGENTS.is_dir(), reason="karos-agents checkout not found beside this repo"
)


# --- Delegation ---------------------------------------------------------------


def test_task_tool_dispatch_becomes_an_independent_task() -> None:
    text = 'dispatch each one via the Task tool with `subagent_type: "research"` and wait'

    out, applied = neutralize(text)

    assert "Task tool" not in out
    assert "subagent_type" not in out
    assert "run each as an independent research task" in out
    # The trailing clause is not collateral damage.
    assert out.endswith("and wait")
    assert "task-tool-dispatch" in applied


def test_the_self_containment_warning_survives() -> None:
    """The load-bearing half of that paragraph: workers can't see the thread."""

    text = (
        "keep each delegated prompt self-contained, since the subagent has no "
        "access to this conversation"
    )

    out, _ = neutralize(text)

    assert "self-contained" in out
    assert "no access to this conversation" in out


def test_the_cost_tier_hint_survives_as_a_tier_not_a_name() -> None:
    text = "the platform may route this name to a cost-tier model"

    out, _ = neutralize(text)

    assert "lower-cost model tier" in out


def test_fan_out_phrasing_avoids_the_research_stutter() -> None:
    """x-agent's sentence already says 'for research'."""

    text = (
        "Fan out parallel sub-agents for research — dispatch each one via the "
        'Task tool with `subagent_type: "research"`'
    )

    out, _ = neutralize(text)

    assert "parallel delegated tasks for research" in out
    assert "research tasks for research" not in out


# --- Built-in tools -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("treat WebSearch/WebFetch as the fallback", "web search / web fetch"),
        ("Use WebSearch + WebFetch and any RSS", "web search + web fetch"),
        ("- **WebSearch / WebFetch (fallback).**", "web search / web fetch"),
        ("`pdf` skill / WebFetch if hosted", "web fetch"),
        ("fall back to a sibling leg / WebSearch, mark it", "web search"),
    ],
)
def test_builtin_tool_names_become_capabilities(text: str, expected: str) -> None:
    out, _ = neutralize(text)

    assert expected in out
    assert "WebSearch" not in out and "WebFetch" not in out


def test_the_reddit_fetch_block_note_still_makes_sense() -> None:
    """This one carries a real operational fact, not just a tool name."""

    text = "Reddit blocks direct fetches (`.json` returns 403, WebFetch of reddit.com is blocked)"

    out, _ = neutralize(text)

    assert "web fetch of reddit.com is blocked" in out
    assert "403" in out


# --- Skills path --------------------------------------------------------------


def test_claude_skills_path_becomes_a_generic_global_directory() -> None:
    text = "never `~/.claude/skills/` — client machinery lives in the client folder"

    out, _ = neutralize(text)

    assert ".claude/skills" not in out
    assert "never a global or user-level skill directory" in out
    # The actual rule — where machinery *does* live — is untouched.
    assert "client machinery lives in the client folder" in out


# --- Model routing ------------------------------------------------------------


def test_model_ids_become_tiers() -> None:
    text = "declares `model: claude-sonnet-5` and the strategy layer (`model: claude-opus-4-8`:"

    out, _ = neutralize(text)

    assert "claude-sonnet" not in out and "claude-opus" not in out
    assert "`model_tier: standard`" in out
    assert "`model_tier: reasoning`" in out


def test_the_cost_guardrail_survives_the_rename() -> None:
    """'Never draft posts on Opus' is a real spend rule, not a Claude detail."""

    text = "Opus is reserved for the manager's strategy layer. Never draft posts on Opus."

    out, _ = neutralize(text)

    assert "Opus" not in out
    assert "The reasoning tier is reserved for" in out
    assert "Never draft posts on the reasoning tier." in out


def test_the_two_tier_drafting_split_survives() -> None:
    text = "the executable engine drafts on Sonnet 5 (Haiku for triage)."

    out, _ = neutralize(text)

    assert "Sonnet" not in out and "Haiku" not in out
    assert "drafts on the standard tier (a fast tier for triage)" in out


# --- Whole-corpus properties --------------------------------------------------


def test_clean_text_is_left_completely_alone() -> None:
    text = "Write one post. Cite every number. Never invent a statistic."

    out, applied = neutralize(text)

    assert out == text
    assert applied == []


def test_neutralize_is_idempotent() -> None:
    """Re-running over already-clean output must not churn it further."""

    text = (
        "Fan out parallel sub-agents — dispatch each one via the Task tool "
        'with `subagent_type: "research"`, or WebSearch.'
    )

    once, _ = neutralize(text)
    twice, applied_again = neutralize(once)

    assert once == twice
    assert applied_again == []


def test_every_rule_has_a_stated_rationale() -> None:
    """A substitution nobody can justify should not be in the list."""

    for rule in RULES:
        assert rule.why.strip(), f"rule {rule.name} has no rationale"
        assert rule.name.strip()


@needs_lab_repo
def test_the_whole_corpus_is_clean_after_neutralisation() -> None:
    """The acceptance test for Task 1: --strict has nothing left to report."""

    remaining: list[str] = []
    for spec in AGENT_SPECS:
        content, _ = compose_prompt(KAROS_AGENTS, spec, apply_neutralize=True)
        for label in find_claude_isms(content):
            remaining.append(f"{spec.slug}: {label}")

    assert remaining == [], f"harness content survived neutralisation: {remaining}"


@needs_lab_repo
def test_neutralisation_can_be_turned_off() -> None:
    """--no-neutralize must genuinely seed the raw legacy text."""

    spec = next(s for s in AGENT_SPECS if s.slug == "x-agent")

    raw, applied = compose_prompt(KAROS_AGENTS, spec, apply_neutralize=False)

    assert applied == []
    assert find_claude_isms(raw), "expected the raw x-agent prompt to still be dirty"


@needs_lab_repo
def test_neutralisation_does_not_gut_the_prompts() -> None:
    """A rule that deleted rather than substituted would show up as shrinkage."""

    for spec in AGENT_SPECS:
        raw, _ = compose_prompt(KAROS_AGENTS, spec, apply_neutralize=False)
        clean, _ = compose_prompt(KAROS_AGENTS, spec, apply_neutralize=True)

        # Substitutions shift length slightly; anything beyond 1% means a rule
        # is removing content rather than rewording it.
        assert abs(len(clean) - len(raw)) / len(raw) < 0.01, (
            f"{spec.slug}: length changed from {len(raw)} to {len(clean)}"
        )

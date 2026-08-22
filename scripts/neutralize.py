"""Rewrite harness-specific vocabulary out of legacy prompts, at migration time.

Why here and not in ``karos-agents``
------------------------------------
The obvious move is to fix the source files. Two things rule it out:

1. **The lab repo is still live.** ``karosCMO/src/lib/agent-service/
   custom-agent-import.ts`` reads it from GitHub, and those same ``SKILL.md``
   bodies are what the currently-running agent-service executes for the X,
   LinkedIn and Reddit agents. That runner *does* have ``WebSearch`` and the
   Task tool. Rewriting "use WebSearch" into "use web search" there would
   degrade a working production system in order to tidy up its replacement.
2. The local checkout is dozens of commits behind a remote that is slow to
   fetch, so committing against it risks clobbering other people's work.

Doing it at migration time keeps the legacy runner working, keeps the rules
version-controlled and testable, and makes the transformation reversible
(``--no-neutralize`` seeds the raw text).

Why this is not the regex sweep I refused to write
--------------------------------------------------
The seeder deliberately does not *delete* prose it doesn't like: a pattern that
dropped a sentence containing "Task tool" would take a real instruction with it
and leave a prompt that reads fine and behaves wrong.

These rules are the opposite shape. Each one is hand-written against a specific
observed phrase, replaces it with an equivalent that preserves the instruction,
and is pinned by a test asserting the meaning survives. Nothing is deleted;
vocabulary is substituted.

The safety net is that :func:`find_claude_isms` still runs on the *output*. If a
rule under-covers — a phrasing variant nobody anticipated — the detector fires
and ``--strict`` fails the run. Coverage is therefore self-verifying rather than
assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NeutralizeRule:
    """One reviewed substitution."""

    name: str
    pattern: re.Pattern[str]
    replacement: str
    why: str


def _rule(name: str, pattern: str, replacement: str, why: str, *, flags: int = 0) -> NeutralizeRule:
    return NeutralizeRule(name, re.compile(pattern, flags), replacement, why)


# Order matters: compound forms ("WebSearch/WebFetch") must be rewritten before
# the single-token rules would chew them up piecemeal.
RULES: tuple[NeutralizeRule, ...] = (
    # --- Delegation: the Task tool / subagent_type construct ----------------
    _rule(
        "task-tool-dispatch",
        r"dispatch each one via the Task tool with `subagent_type: \"research\"`",
        "run each as an independent research task",
        "Names a Claude-specific tool and its argument; the instruction is just "
        "'delegate these in parallel'.",
    ),
    _rule(
        "task-tool-cost-tier",
        r"the platform may route this name to a cost-tier model",
        "the runtime may route these to a lower-cost model tier",
        "'this name' referred to subagent_type; the real point is tier routing.",
    ),
    _rule(
        "subagent-no-context",
        r"the subagent has no access to this conversation",
        "a delegated task has no access to this conversation",
        "Keeps the load-bearing 'make each prompt self-contained' warning.",
    ),
    _rule(
        "parallel-subagents",
        r"\bparallel sub-agents\b",
        "parallel delegated tasks",
        "Provider-neutral name for the same fan-out. Deliberately not 'research "
        "tasks': x-agent's sentence already reads 'for research', and that "
        "produced 'parallel research tasks for research — run each as an "
        "independent research task'.",
    ),
    # --- Built-in tool names -------------------------------------------------
    _rule(
        "websearch-webfetch-slash",
        r"\bWebSearch\s*/\s*WebFetch\b",
        "web search / web fetch",
        "Claude built-in tool names; the capability is what matters.",
    ),
    _rule(
        "websearch-webfetch-plus",
        r"\bWebSearch\s*\+\s*WebFetch\b",
        "web search + web fetch",
        "Same, in the additive phrasing.",
    ),
    _rule(
        "websearch",
        r"\bWebSearch\b",
        "web search",
        "Claude built-in tool name.",
    ),
    _rule(
        "webfetch",
        r"\bWebFetch\b",
        "web fetch",
        "Claude built-in tool name.",
    ),
    # --- Claude Skills filesystem layout ------------------------------------
    _rule(
        "claude-skills-path",
        r"`~/\.claude/skills/`",
        "a global or user-level skill directory",
        "The instruction is 'client machinery belongs in the client folder, not "
        "somewhere global' — true of any runtime.",
    ),
    # --- Model routing: names -> tiers ---------------------------------------
    # The policy being preserved: draft on a standard tier, reserve the
    # expensive reasoning tier for strategy. That survives a provider change;
    # the specific model ids do not.
    _rule(
        "model-id-sonnet",
        r"`model: claude-sonnet-[\w.-]+`",
        "`model_tier: standard`",
        "Pins a specific vendor model; the intent is a capability tier.",
    ),
    _rule(
        "model-id-opus",
        r"`model: claude-opus-[\w.-]+`",
        "`model_tier: reasoning`",
        "Pins a specific vendor model; the intent is a capability tier.",
    ),
    _rule(
        "sonnet-tier-work",
        r"\bSonnet-tier work\b",
        "standard-tier work",
        "Tier described by vendor model name.",
    ),
    _rule(
        "drafts-on-sonnet",
        r"drafts on Sonnet \d+ \(Haiku for triage\)",
        "drafts on the standard tier (a fast tier for triage)",
        "Two vendor model names describing a two-tier split.",
    ),
    _rule(
        "opus-reserved",
        r"\bOpus is reserved for\b",
        "The reasoning tier is reserved for",
        "Tier described by vendor model name.",
    ),
    _rule(
        "never-draft-on-opus",
        r"Never draft posts on Opus\.",
        "Never draft posts on the reasoning tier.",
        "The cost guardrail is real and must survive; only the name changes.",
    ),
)


def neutralize(text: str) -> tuple[str, list[str]]:
    """Apply every rule. Returns the rewritten text and the rules that fired."""

    applied: list[str] = []
    for rule in RULES:
        text, count = rule.pattern.subn(rule.replacement, text)
        if count:
            applied.append(f"{rule.name}x{count}" if count > 1 else rule.name)
    return text, applied

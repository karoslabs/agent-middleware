"""What to migrate out of the legacy ``karos-agents`` repo, declared explicitly.

This is a hand-written manifest rather than a directory crawl, on purpose. The
lab repo mixes three very different things in adjacent folders: reusable craft
guidance, client-specific one-offs, and harness plumbing that only made sense
inside a single-shot Claude skill. A glob would sweep all three into Firestore
and call it a migration. Naming each file means a human decided it was worth
keeping, and a missing path fails loudly instead of silently seeding less than
expected.

Two layout facts worth knowing before editing this file:

* ``reddit-agent`` is **not** under ``products/live/`` — it lives in
  ``products/building/``, and the v2 rewrite (generic runner + data files) is
  the better migration target than v1.
* ``landing-page`` has no ``assets/`` tree at all. Its reusable material is the
  brand-token contract under ``engine/template/``; its page templates are React
  components, which are not template *bodies* in this control plane's sense and
  are therefore out of scope here (agent-engine ships that kit directly).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import TemplateKind


@dataclass(frozen=True)
class TemplateSource:
    """One template to seed, and where its body comes from."""

    slug: str
    name: str
    kind: TemplateKind
    #: Repo-relative path of the body (HTML, CSS, JS or JSON).
    path: str
    #: Bind to the owning agent under this purpose. ``None`` seeds the template
    #: without binding it — useful for an archetype library where only one
    #: entry is the agent's default.
    purpose: str | None = None
    #: Repo-relative paths of binaries this body renders with. Uploaded to GCS;
    #: only the resulting gs:// URIs are stored on the version.
    assets: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class LegacyAgentSpec:
    """One agent to seed, with its prompt sources and templates."""

    slug: str
    name: str
    description: str
    agent_type: str
    #: Repo-relative path of the SKILL.md whose body becomes the system prompt.
    skill_path: str
    #: Reference docs appended to the prompt under their own headings.
    #: Deliberately an explicit list: the lab repo's ``references/`` folders
    #: also hold connector//harness-coupled docs that must NOT be injected into
    #: a model-agnostic prompt (research methodology tied to WebSearch, sourcing
    #: profiles tied to repo paths, sub-skill emission specs).
    reference_paths: tuple[str, ...] = ()
    templates: tuple[TemplateSource, ...] = ()
    tags: tuple[str, ...] = ()
    config: dict[str, object] = field(default_factory=dict)


_IG = "products/live/instagram-agent"
_LP = "products/live/landing-page"
_X = "products/live/x-agent"
_LI = "products/live/linkedin-agent"
_RD = "products/building/reddit-agent-v2"

# The instagram carousel templates all boot through one shared JS runtime and
# device stylesheet; a body seeded without them renders blank. They are seeded
# as their own `other`-kind templates so the set stays complete and versioned
# together, rather than being silently half-migrated.
_IG_RUNTIME: tuple[TemplateSource, ...] = (
    TemplateSource(
        slug="ig-runtime-core",
        name="Instagram carousel runtime (core)",
        kind=TemplateKind.OTHER,
        path=f"{_IG}/assets/templates/_cf-core.js",
        description="CF.baseSlide/CF.boot: the data loader every carousel body calls.",
    ),
    TemplateSource(
        slug="ig-runtime-devices",
        name="Instagram carousel runtime (devices)",
        kind=TemplateKind.OTHER,
        path=f"{_IG}/assets/templates/_cf-devices.js",
        description="Shared slide device widgets.",
    ),
    TemplateSource(
        slug="ig-runtime-devices-css",
        name="Instagram carousel device stylesheet",
        kind=TemplateKind.OTHER,
        path=f"{_IG}/assets/templates/_cf-devices.css",
        description="Brand-agnostic device styling consumed by every carousel body.",
    ),
)

_IG_ARCHETYPES: tuple[TemplateSource, ...] = tuple(
    TemplateSource(
        slug=f"ig-{name}",
        name=f"Instagram · {name.replace('-', ' ')}",
        kind=TemplateKind.HTML_LAYOUT,
        path=f"{_IG}/assets/templates/{name}.html",
        # story-carousel is the default lane; the rest are the archetype library
        # a client build varies from, so only that one claims the purpose.
        purpose="primary" if name == "story-carousel" else None,
    )
    for name in (
        "story-carousel",
        "informational-list",
        "news-pulse",
        "study-fact",
        "verdict-ranking",
    )
)

_IG_MARKETING: tuple[TemplateSource, ...] = (
    TemplateSource(
        slug="ig-ms-core-css",
        name="Instagram · marketing-services tokens",
        kind=TemplateKind.OTHER,
        path=f"{_IG}/assets/templates/marketing-services/_ms-core.css",
        description="Placeholder :root token set a client build overrides wholesale.",
        assets=(f"{_IG}/assets/templates/marketing-services/assets/logo-mark-placeholder.svg",),
    ),
)


AGENT_SPECS: tuple[LegacyAgentSpec, ...] = (
    LegacyAgentSpec(
        slug="instagram-agent",
        name="Instagram Agent",
        description="Builds and runs a client's Instagram carousel system.",
        agent_type="instagram_carousel",
        skill_path=f"{_IG}/SKILL.md",
        reference_paths=(
            f"{_IG}/references/anti-ai-rules.md",
            f"{_IG}/references/taste-design-rules.md",
            f"{_IG}/references/template-archetypes.md",
            f"{_IG}/references/brand-schema.md",
            f"{_IG}/references/weekly-news-format.md",
            f"{_IG}/references/localization-and-immersion.md",
        ),
        templates=(
            *_IG_ARCHETYPES,
            *_IG_RUNTIME,
            *_IG_MARKETING,
            TemplateSource(
                slug="ig-format-recipes",
                name="Instagram format recipes",
                kind=TemplateKind.JSON_SCHEMA,
                path=f"{_IG}/assets/formats/format-recipes.json",
                purpose="formats",
                description="Brand-agnostic slide-brick recipes and their sample payloads.",
            ),
        ),
        tags=("social", "instagram", "carousel"),
    ),
    LegacyAgentSpec(
        slug="landing-builder-agent",
        name="Landing Builder Agent",
        description="Builds a client landing page from a brand contract and intake.",
        agent_type="landing_page",
        skill_path=f"{_LP}/landing-builder/SKILL.md",
        reference_paths=(
            f"{_LP}/ENGINE-SPEC.md",
            f"{_LP}/landing-taste/SKILL.md",
            f"{_LP}/ui-ux-pro-max-rules/SKILL.md",
            f"{_LP}/docs/landing-build-system/BRAND-FIT-RUBRIC.md",
        ),
        templates=(
            TemplateSource(
                slug="landing-brand-contract",
                name="Landing brand contract",
                kind=TemplateKind.JSON_SCHEMA,
                path=f"{_LP}/engine/template/brand.json",
                purpose="brand",
                description="Token/identity/voice contract every landing build is generated from.",
            ),
            TemplateSource(
                slug="landing-globals-css",
                name="Landing global tokens",
                kind=TemplateKind.OTHER,
                path=f"{_LP}/engine/template/src/app/globals.css",
                purpose="primary",
                description="The per-client skin lever: CSS custom properties only.",
            ),
        ),
        tags=("web", "landing-page"),
    ),
    LegacyAgentSpec(
        slug="x-agent",
        name="X Agent",
        description="Drafts X posts and threads in a client's voice. Draft-only.",
        agent_type="x_post",
        skill_path=f"{_X}/SKILL.md",
        reference_paths=(
            f"{_X}/references/x-craft.md",
            f"{_X}/references/x-growth-playbook.md",
        ),
        tags=("social", "x", "draft-only"),
    ),
    LegacyAgentSpec(
        slug="linkedin-agent",
        name="LinkedIn Agent",
        description="Drafts LinkedIn posts for a company page or an executive. Draft-only.",
        agent_type="linkedin_post",
        skill_path=f"{_LI}/SKILL.md",
        reference_paths=(
            f"{_LI}/references/linkedin-voice-by-industry.md",
            f"{_LI}/references/founder-persona-spec.md",
            f"{_LI}/references/company-page-spec.md",
        ),
        tags=("social", "linkedin", "draft-only"),
    ),
    LegacyAgentSpec(
        slug="reddit-agent",
        name="Reddit Agent",
        description=(
            "Drafts one Reddit reply to an existing thread. Draft-only as a hard "
            "product rule: a human always posts from their own account."
        ),
        agent_type="reddit_reply",
        skill_path=f"{_RD}/SKILL.md",
        reference_paths=(
            f"{_RD}/references/reddit-craft.md",
            f"{_RD}/references/run-protocol.md",
        ),
        templates=(
            TemplateSource(
                slug="reddit-account-state",
                name="Reddit account state",
                kind=TemplateKind.JSON_SCHEMA,
                path=f"{_RD}/assets/templates/account-template.json",
                purpose="account",
                description="Per-account mode/mentions/disclosure — feeds three ban-risk gates.",
            ),
            TemplateSource(
                slug="reddit-rules-audit",
                name="Reddit subreddit rules audit",
                kind=TemplateKind.JSON_SCHEMA,
                path=f"{_RD}/assets/templates/rules-audit-template.json",
                purpose="rules",
                description="Per-subreddit promo verdict, karma/age gates, AI-content ban.",
            ),
            TemplateSource(
                slug="reddit-scan-config",
                name="Reddit scan config",
                kind=TemplateKind.JSON_SCHEMA,
                path=f"{_RD}/assets/templates/scan-config-template.json",
                purpose="scan",
                description="Thread-discovery parameters. No secrets.",
            ),
            TemplateSource(
                slug="reddit-ledger",
                name="Reddit continuity ledger",
                kind=TemplateKind.JSON_SCHEMA,
                path=f"{_RD}/assets/templates/ledger-template.json",
                purpose="ledger",
                description="Append-only cross-account continuity record.",
            ),
        ),
        # Draft-only is a product rule, not a preference — carried onto the agent
        # document so it travels in every dispatched payload.
        config={"draft_only": True, "replies_only": True},
        tags=("social", "reddit", "draft-only"),
    ),
)

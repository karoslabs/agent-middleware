"""Assembles the full context of an agent for injection into a job.

This is the endpoint the portal calls at launch time: one read that resolves the
agent's settings, its active system prompt, its active few-shot examples and the
active version of the template bound to the requested purpose. The engine then
works from that document alone -- it never talks to Firestore.
"""

from __future__ import annotations

import logging
from typing import Any

from app.api.schemas.context import (
    AgentContext,
    AgentContextAgent,
    AgentContextExample,
    AgentContextPrompt,
    AgentContextTemplate,
)
from app.api.schemas.presentation import AgentStage
from app.config import Settings
from app.core.exceptions import IncompleteAgentConfigurationError
from app.db.firestore import utcnow
from app.services.agents import AgentService
from app.services.prompts import PromptService
from app.services.templates import DEFAULT_PURPOSE, TemplateService

logger = logging.getLogger(__name__)


class ContextService:
    """Resolves everything dynamic about an agent into one snapshot."""

    def __init__(
        self,
        settings: Settings,
        agents: AgentService,
        prompts: PromptService,
        templates: TemplateService,
    ) -> None:
        self._settings = settings
        self._agents = agents
        self._prompts = prompts
        self._templates = templates

    async def build(
        self,
        agent_ref: str,
        *,
        purpose: str = DEFAULT_PURPOSE,
        template_ref: str | None = None,
        include_examples: bool = True,
        max_examples: int | None = None,
        require_active: bool = False,
    ) -> AgentContext:
        """Resolve the context of an agent.

        ``require_active`` refuses disabled agents; it is set when the context is
        about to become a real job, and left off for portal previews.
        """

        agent = (
            await self._agents.get_active(agent_ref)
            if require_active
            else await self._agents.get(agent_ref)
        )
        agent_id = agent["id"]

        prompt = await self._prompts.find_active(agent_id)
        limit = (
            max_examples
            if max_examples is not None
            else self._settings.default_context_example_limit
        )
        examples = await self._prompts.context_examples(agent_id, limit) if include_examples else []
        resolved_template = await self._templates.resolve_for_agent(
            agent_id, purpose=purpose, template_ref=template_ref
        )

        return AgentContext(
            agent=AgentContextAgent(
                id=agent_id,
                slug=agent["slug"],
                name=agent["name"],
                status=agent["status"],
                agent_type=agent.get("agent_type"),
                model=agent.get("model"),
                model_params=agent.get("model_params") or {},
                config=agent.get("config") or {},
                tags=agent.get("tags") or [],
                stages=[AgentStage.model_validate(st) for st in (agent.get("stages") or [])],
            ),
            system_prompt=_to_context_prompt(prompt),
            few_shot_examples=[_to_context_example(example) for example in examples],
            template=_to_context_template(resolved_template, purpose),
            resolved_at=utcnow(),
        )

    async def build_runnable(
        self,
        agent_ref: str,
        *,
        purpose: str = DEFAULT_PURPOSE,
        template_ref: str | None = None,
        include_examples: bool = True,
        max_examples: int | None = None,
    ) -> AgentContext:
        """Like :meth:`build`, but rejects a context that cannot produce a job."""

        context = await self.build(
            agent_ref,
            purpose=purpose,
            template_ref=template_ref,
            include_examples=include_examples,
            max_examples=max_examples,
            require_active=True,
        )
        if context.system_prompt is None:
            raise IncompleteAgentConfigurationError(
                f"agent '{agent_ref}' has no active system prompt; publish one before "
                "dispatching a job"
            )
        return context


def _to_context_prompt(prompt: dict[str, Any] | None) -> AgentContextPrompt | None:
    if prompt is None:
        return None
    return AgentContextPrompt(
        id=prompt["id"],
        version=prompt["version"],
        content=prompt["content"],
        variables=prompt.get("variables") or [],
    )


def _to_context_example(example: dict[str, Any]) -> AgentContextExample:
    return AgentContextExample(
        id=example["id"],
        label=example.get("label"),
        user_input=example["user_input"],
        assistant_output=example["assistant_output"],
        tags=example.get("tags") or [],
    )


def _to_context_template(
    resolved: tuple[dict[str, Any], dict[str, Any]] | None, purpose: str
) -> AgentContextTemplate | None:
    if resolved is None:
        return None

    template, version = resolved
    return AgentContextTemplate(
        id=template["id"],
        slug=template["slug"],
        name=template["name"],
        kind=template["kind"],
        purpose=purpose,
        version_id=version["id"],
        version=version["version"],
        content=version.get("content"),
        schema_definition=version.get("schema_definition"),
        variables=version.get("variables") or [],
        # `or []` rather than a plain .get default: a version written before
        # assets existed has no key, and one written with an explicit null
        # should read back as empty rather than blowing up validation.
        assets=version.get("assets") or [],
    )

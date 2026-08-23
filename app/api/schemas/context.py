"""The agent context envelope and the job payload built from it.

This is the contract between the portal, the middleware and the engine: the
middleware resolves everything dynamic (active prompt, examples, template
version) into one self-contained document, and the engine works from that
document alone -- it never reads this database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.api.schemas.presentation import AgentStage
from app.api.schemas.run import RunRead
from app.core.enums import AgentStatus, TemplateKind

JOB_PAYLOAD_SCHEMA_VERSION = 1

#: agent-engine's own `RunKindSchema`. A fresh client's first build is "setup";
#: everything after it is "recurring".
RunKind = Literal["setup", "recurring"]


class AgentContextAgent(BaseModel):
    """Agent-level settings the engine needs."""

    id: str
    slug: str
    name: str
    status: AgentStatus
    agent_type: str | None
    model: str | None
    model_params: dict[str, Any]
    config: dict[str, Any]
    tags: list[str]
    #: The agent's stages, carried so the dispatch can flatten any per-stage
    #: model choices into the engine's `stageModels` map. Only the stages
    #: matter here, not their labels -- but the whole list travels rather than
    #: a pre-flattened map, so the payload stays a description of the agent
    #: rather than of one derived view of it.
    stages: list[AgentStage] = Field(default_factory=list)


class AgentContextPrompt(BaseModel):
    """The active system prompt at resolution time."""

    id: str
    version: int
    content: str
    variables: list[str]


class AgentContextExample(BaseModel):
    """A few-shot example, flattened for the engine."""

    id: str
    label: str | None
    user_input: str
    assistant_output: str
    tags: list[str]


class AgentContextTemplate(BaseModel):
    """The resolved template and the exact version to render."""

    id: str
    slug: str
    name: str
    kind: TemplateKind
    purpose: str
    version_id: str
    version: int
    content: str | None
    schema_definition: dict[str, Any] | None
    variables: list[str]
    assets: list[str] = Field(
        default_factory=list,
        description=(
            "GCS URIs of the binary assets bound to this template version. The "
            "engine fetches these itself; only the references travel in the payload."
        ),
    )


class AgentContext(BaseModel):
    """Everything needed to run an agent, resolved at a point in time."""

    agent: AgentContextAgent
    system_prompt: AgentContextPrompt | None
    few_shot_examples: list[AgentContextExample] = Field(default_factory=list)
    template: AgentContextTemplate | None
    resolved_at: datetime


class JobPayload(AgentContext):
    """The message body published to the engine topic.

    A superset of :class:`AgentContext`: same resolved configuration, plus the
    per-job identity and inputs supplied by the caller.

    Note the routing trio below. agent-engine's own ``RunJobRequestSchema``
    reads ``clientSlug`` / ``productId`` / ``runKind`` off the **top level** of
    the message, in camelCase, and rejects a message without them. They are
    held here in this module's snake_case and renamed on the wire by
    :func:`app.services.dispatch.to_engine_message` — see that function for why
    the message carries two shapes at once.
    """

    schema_version: int = JOB_PAYLOAD_SCHEMA_VERSION
    run_id: str
    job_type: str | None
    input: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None
    dispatched_at: datetime

    client_slug: str = Field(description="Tenant the engine resolves its workspace against")
    product_id: str = Field(description="Engine workflow to run; the agent's slug")
    run_kind: RunKind = Field(default="recurring")


class DispatchRequest(BaseModel):
    """Body for ``POST /agents/{agent_ref}/jobs``.

    Lets the middleware do the assembling *and* the publishing, for callers that
    would rather not build the payload themselves.
    """

    client_slug: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Tenant this job runs for. Required: the engine resolves the client's "
            "whole workspace from it, and there is no safe default."
        ),
    )
    run_kind: RunKind = Field(default="recurring", description="'setup' for a client's first build")
    run_id: str | None = Field(
        default=None, max_length=64, description="Caller-owned run id; generated when omitted"
    )
    job_type: str | None = Field(default=None, max_length=64)
    input: dict[str, Any] = Field(
        default_factory=dict, description="Job-specific variables merged into the payload"
    )
    template_purpose: str = Field(default="primary", max_length=64)
    template_ref: str | None = Field(
        default=None, description="Template id or slug, overriding the agent binding"
    )
    include_examples: bool = True
    max_examples: int | None = Field(default=None, ge=0, le=200)
    requested_by: str | None = Field(default=None, max_length=255)
    attributes: dict[str, str] = Field(
        default_factory=dict, description="Extra Pub/Sub message attributes"
    )


class DispatchResponse(BaseModel):
    """Result of publishing a job to the engine topic."""

    run: RunRead
    topic: str
    pubsub_message_id: str

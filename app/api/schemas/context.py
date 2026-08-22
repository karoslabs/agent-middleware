"""The agent context envelope and the job payload built from it.

This is the contract between the portal, the middleware and the engine: the
middleware resolves everything dynamic (active prompt, examples, template
version) into one self-contained document, and the engine works from that
document alone -- it never reads this database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.api.schemas.run import RunRead
from app.core.enums import AgentStatus, TemplateKind

JOB_PAYLOAD_SCHEMA_VERSION = 1


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
    """

    schema_version: int = JOB_PAYLOAD_SCHEMA_VERSION
    run_id: str
    job_type: str | None
    input: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = None
    dispatched_at: datetime


class DispatchRequest(BaseModel):
    """Body for ``POST /agents/{agent_ref}/jobs``.

    Lets the middleware do the assembling *and* the publishing, for callers that
    would rather not build the payload themselves.
    """

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

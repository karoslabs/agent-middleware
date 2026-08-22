"""Template and template-version schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.api.schemas.common import SlugStr
from app.core.enums import TemplateKind


class TemplateCreate(BaseModel):
    """Body for ``POST /templates``.

    An initial version can be supplied inline so a template never exists in a
    useless bodyless state.
    """

    slug: SlugStr
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    kind: TemplateKind = TemplateKind.OTHER
    tags: list[str] = Field(default_factory=list)

    content: str | None = Field(default=None, description="Initial version body (optional)")
    schema_definition: dict[str, Any] | None = Field(
        default=None, description="Initial version structure/settings (optional)"
    )
    variables: list[str] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    """Body for ``PATCH /templates/{template_ref}`` (metadata only).

    Bodies are versioned, so changing content means posting a new version.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    kind: TemplateKind | None = None
    tags: list[str] | None = None


class TemplateVersionCreate(BaseModel):
    """Body for ``POST /templates/{template_ref}/versions``."""

    content: str | None = None
    schema_definition: dict[str, Any] | None = None
    variables: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_by: str | None = Field(default=None, max_length=255)
    activate: bool = True

    @model_validator(mode="after")
    def require_a_body(self) -> TemplateVersionCreate:
        if self.content is None and self.schema_definition is None:
            raise ValueError("either 'content' or 'schema_definition' must be provided")
        return self


class TemplateVersionRead(BaseModel):
    """One immutable template version."""

    id: str
    template_id: str
    version: int
    content: str | None
    schema_definition: dict[str, Any] | None
    variables: list[str]
    notes: str | None
    is_active: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class TemplateRead(BaseModel):
    """Template metadata, without any version body.

    Returned by list endpoints. Fetching a single template returns
    :class:`TemplateDetail`, which carries the bodies too.
    """

    id: str
    slug: str
    name: str
    description: str | None
    kind: TemplateKind
    tags: list[str]
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TemplateDetail(TemplateRead):
    """A template with its active version and full version history."""

    active_version: TemplateVersionRead | None = None
    versions: list[TemplateVersionRead] = Field(default_factory=list)


class AgentTemplateLinkCreate(BaseModel):
    """Body for ``PUT /agents/{agent_ref}/templates/{purpose}``.

    The purpose is the path key because an agent uses exactly one template per
    purpose -- it is the link document id, so the constraint is structural.
    """

    template_ref: str = Field(
        min_length=1, max_length=128, description="Template id (its slug)"
    )
    is_primary: bool = True


class AgentTemplateLinkRead(BaseModel):
    """A template bound to an agent."""

    id: str
    agent_id: str
    template_id: str
    purpose: str
    is_primary: bool
    created_at: datetime
    updated_at: datetime
    template: TemplateRead | None = Field(
        default=None, description="Metadata of the bound template, when it still exists"
    )

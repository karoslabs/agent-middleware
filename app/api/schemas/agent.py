"""Agent CRUD schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.api.schemas.common import SlugStr
from app.core.enums import AgentStatus


class AgentCreate(BaseModel):
    """Body for ``POST /agents``."""

    slug: SlugStr
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: AgentStatus = AgentStatus.ACTIVE
    agent_type: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    model_params: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    """Body for ``PATCH /agents/{agent_ref}``; unset fields are left untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: AgentStatus | None = None
    agent_type: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    model_params: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    tags: list[str] | None = None


class AgentStatusUpdate(BaseModel):
    """Body for ``PATCH /agents/{agent_ref}/status``."""

    status: AgentStatus


class AgentRead(BaseModel):
    """An agent as returned by the API."""

    id: str
    slug: str
    name: str
    description: str | None
    status: AgentStatus
    agent_type: str | None
    model: str | None
    model_params: dict[str, Any]
    config: dict[str, Any]
    tags: list[str]
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

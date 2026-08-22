"""Agent CRUD: the portal's registry of agents.

``agent_id`` in every path is the agent's slug -- it is the Firestore document
id, so the two are the same value.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.schemas.agent import AgentCreate, AgentRead, AgentStatusUpdate, AgentUpdate
from app.api.schemas.common import Page, Pagination, pagination, parse_rows
from app.core.enums import AgentStatus
from app.dependencies import get_agent_service
from app.services.agents import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent",
)
async def create_agent(
    payload: AgentCreate,
    agents: AgentService = Depends(get_agent_service),
) -> AgentRead:
    agent = await agents.create(payload)
    return AgentRead.model_validate(agent)


@router.get("", response_model=Page[AgentRead], summary="List agents")
async def list_agents(
    page: Pagination = Depends(pagination),
    agent_status: Annotated[AgentStatus | None, Query(alias="status")] = None,
    agent_type: Annotated[str | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    q: Annotated[
        str | None, Query(description="Free-text match on slug, name, description")
    ] = None,
    include_deleted: Annotated[bool, Query()] = False,
    agents: AgentService = Depends(get_agent_service),
) -> Page[AgentRead]:
    items, total = await agents.list_agents(
        status=agent_status,
        agent_type=agent_type,
        tag=tag,
        query=q,
        include_deleted=include_deleted,
        limit=page.limit,
        offset=page.offset,
    )
    return Page[AgentRead](
        items=parse_rows(AgentRead, items, collection="agents"),
        limit=page.limit,
        offset=page.offset,
        total=total,
        has_more=page.offset + len(items) < total,
    )


@router.get("/{agent_id}", response_model=AgentRead, summary="Get one agent")
async def get_agent(
    agent_id: str,
    include_deleted: Annotated[bool, Query()] = False,
    agents: AgentService = Depends(get_agent_service),
) -> AgentRead:
    agent = await agents.get(agent_id, include_deleted=include_deleted)
    return AgentRead.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentRead, summary="Update an agent")
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    agents: AgentService = Depends(get_agent_service),
) -> AgentRead:
    agent = await agents.update(agent_id, payload)
    return AgentRead.model_validate(agent)


@router.patch(
    "/{agent_id}/status",
    response_model=AgentRead,
    summary="Enable or disable an agent",
    description="A disabled agent can still be read and edited, but not dispatched.",
)
async def set_agent_status(
    agent_id: str,
    payload: AgentStatusUpdate,
    agents: AgentService = Depends(get_agent_service),
) -> AgentRead:
    agent = await agents.set_status(agent_id, payload.status)
    return AgentRead.model_validate(agent)


@router.delete(
    "/{agent_id}",
    response_model=AgentRead,
    summary="Logically delete an agent",
    description=(
        "Stamps ``deleted_at`` and disables the agent. The document is kept so "
        "existing runs and feedback stay resolvable."
    ),
)
async def delete_agent(
    agent_id: str,
    agents: AgentService = Depends(get_agent_service),
) -> AgentRead:
    agent = await agents.soft_delete(agent_id)
    return AgentRead.model_validate(agent)


@router.post(
    "/{agent_id}/restore",
    response_model=AgentRead,
    summary="Undo a logical delete",
)
async def restore_agent(
    agent_id: str,
    agents: AgentService = Depends(get_agent_service),
) -> AgentRead:
    agent = await agents.restore(agent_id)
    return AgentRead.model_validate(agent)

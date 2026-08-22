"""Dynamic content templates: HTML layouts, JSON structures, post/page settings.

Two routers live here:

* ``/templates`` -- the template library itself, versioned like prompts.
* ``/agents/{agent_id}/templates`` -- which template an agent uses for which
  purpose. The purpose is the path key because it is the binding's document id,
  so an agent can only ever have one template per purpose.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.schemas.common import OperationResult, Page, Pagination, pagination, parse_rows
from app.api.schemas.template import (
    AgentTemplateLinkCreate,
    AgentTemplateLinkRead,
    TemplateCreate,
    TemplateDetail,
    TemplateRead,
    TemplateUpdate,
    TemplateVersionCreate,
    TemplateVersionRead,
)
from app.core.enums import TemplateKind
from app.dependencies import get_template_service, resolve_agent
from app.services.templates import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])
agent_router = APIRouter(prefix="/agents/{agent_id}/templates", tags=["templates"])


# --- Template library ------------------------------------------------------


@router.post(
    "",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a template",
    description=(
        "Supplying ``content`` or ``schema_definition`` also creates version 1 "
        "and activates it."
    ),
)
async def create_template(
    payload: TemplateCreate,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateRead:
    template = await templates.create(payload)
    return TemplateRead.model_validate(template)


@router.get("", response_model=Page[TemplateRead], summary="List templates")
async def list_templates(
    page: Pagination = Depends(pagination),
    kind: Annotated[TemplateKind | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    q: Annotated[
        str | None, Query(description="Free-text match on slug, name, description")
    ] = None,
    include_deleted: Annotated[bool, Query()] = False,
    templates: TemplateService = Depends(get_template_service),
) -> Page[TemplateRead]:
    items, total = await templates.list_templates(
        kind=kind,
        tag=tag,
        query=q,
        include_deleted=include_deleted,
        limit=page.limit,
        offset=page.offset,
    )
    return Page[TemplateRead](
        items=parse_rows(TemplateRead, items, collection="templates"),
        limit=page.limit,
        offset=page.offset,
        total=total,
        has_more=page.offset + len(items) < total,
    )


@router.get(
    "/{template_id}",
    response_model=TemplateDetail,
    summary="Get a template with its versions",
)
async def get_template(
    template_id: str,
    include_deleted: Annotated[bool, Query()] = False,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateDetail:
    template = await templates.get_detail(template_id, include_deleted=include_deleted)
    return TemplateDetail.model_validate(template)


@router.patch(
    "/{template_id}",
    response_model=TemplateRead,
    summary="Update template metadata",
    description="Bodies are versioned; post a new version to change content.",
)
async def update_template(
    template_id: str,
    payload: TemplateUpdate,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateRead:
    template = await templates.update(template_id, payload)
    return TemplateRead.model_validate(template)


@router.delete(
    "/{template_id}",
    response_model=TemplateRead,
    summary="Logically delete a template",
)
async def delete_template(
    template_id: str,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateRead:
    template = await templates.soft_delete(template_id)
    return TemplateRead.model_validate(template)


@router.post(
    "/{template_id}/restore",
    response_model=TemplateRead,
    summary="Undo a logical delete",
)
async def restore_template(
    template_id: str,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateRead:
    template = await templates.restore(template_id)
    return TemplateRead.model_validate(template)


# --- Template versions -----------------------------------------------------


@router.post(
    "/{template_id}/versions",
    response_model=TemplateVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a new template version",
)
async def create_template_version(
    template_id: str,
    payload: TemplateVersionCreate,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateVersionRead:
    version = await templates.create_version(template_id, payload)
    return TemplateVersionRead.model_validate(version)


@router.get(
    "/{template_id}/versions",
    response_model=list[TemplateVersionRead],
    summary="List template versions, newest first",
)
async def list_template_versions(
    template_id: str,
    templates: TemplateService = Depends(get_template_service),
) -> list[TemplateVersionRead]:
    versions = await templates.list_versions(template_id)
    return [TemplateVersionRead.model_validate(version) for version in versions]


@router.get(
    "/{template_id}/versions/{version}",
    response_model=TemplateVersionRead,
    summary="Get one template version",
)
async def get_template_version(
    template_id: str,
    version: int,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateVersionRead:
    template_version = await templates.get_version(template_id, version)
    return TemplateVersionRead.model_validate(template_version)


@router.post(
    "/{template_id}/versions/{version}/activate",
    response_model=TemplateVersionRead,
    summary="Make a template version the active one",
)
async def activate_template_version(
    template_id: str,
    version: int,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateVersionRead:
    template_version = await templates.activate_version(template_id, version)
    return TemplateVersionRead.model_validate(template_version)


# --- Agent bindings --------------------------------------------------------


@agent_router.get(
    "",
    response_model=list[AgentTemplateLinkRead],
    summary="List the templates bound to an agent",
)
async def list_agent_templates(
    agent: dict[str, Any] = Depends(resolve_agent),
    templates: TemplateService = Depends(get_template_service),
) -> list[AgentTemplateLinkRead]:
    links = await templates.list_agent_links(agent["id"])
    return [AgentTemplateLinkRead.model_validate(link) for link in links]


@agent_router.put(
    "/{purpose}",
    response_model=AgentTemplateLinkRead,
    summary="Bind a template to an agent for a purpose",
    description=(
        "Idempotent: binding a purpose again replaces the previous choice. "
        "``purpose=primary`` is what the context endpoint resolves by default."
    ),
)
async def bind_agent_template(
    purpose: str,
    payload: AgentTemplateLinkCreate,
    agent: dict[str, Any] = Depends(resolve_agent),
    templates: TemplateService = Depends(get_template_service),
) -> AgentTemplateLinkRead:
    link = await templates.bind_to_agent(agent["id"], purpose, payload)
    return AgentTemplateLinkRead.model_validate(link)


@agent_router.delete(
    "/{purpose}",
    response_model=OperationResult,
    summary="Unbind a template from an agent",
)
async def unbind_agent_template(
    purpose: str,
    agent: dict[str, Any] = Depends(resolve_agent),
    templates: TemplateService = Depends(get_template_service),
) -> OperationResult:
    await templates.unbind_from_agent(agent["id"], purpose)
    return OperationResult(detail=f"template binding '{purpose}' removed")

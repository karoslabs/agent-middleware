"""The normalized model catalog.

An agent stage references a ``modelId`` from here instead of carrying a loose
model string, so "which models can this deployment actually run" has one answer
rather than one per author.

Models that Vertex offers but this deployment does not route are listed too,
marked ``not_enabled``. The Studio shows them disabled with a way to ask for
them, which is the difference between "we do not run that" and "that does not
exist".
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.schemas.common import Page, Pagination, pagination, parse_rows
from app.api.schemas.model import (
    ModelAccessRequest,
    ModelAccessRequestRead,
    ModelCreate,
    ModelRead,
    ModelUpdate,
)
from app.core.enums import ModelAvailability
from app.core.roles import Role
from app.dependencies import get_model_service
from app.security import require_role
from app.services.models import ModelService

router = APIRouter(prefix="/models", tags=["models"])


@router.post(
    "",
    response_model=ModelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a model",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def create_model(
    payload: ModelCreate,
    models: ModelService = Depends(get_model_service),
) -> ModelRead:
    return ModelRead.model_validate(await models.create(payload))


@router.get("", response_model=Page[ModelRead], summary="List models")
async def list_models(
    page: Annotated[Pagination, Depends(pagination)],
    availability: Annotated[
        ModelAvailability | None,
        Query(description="Filter to one availability state; omit for the whole catalog"),
    ] = None,
    models: ModelService = Depends(get_model_service),
) -> Page[ModelRead]:
    rows, total = await models.list(
        limit=page.limit, offset=page.offset, availability=availability
    )
    items = parse_rows(ModelRead, rows, collection="models")
    skipped = len(rows) - len(items)
    return Page[ModelRead](
        items=items,
        limit=page.limit,
        offset=page.offset,
        # Excludes rows this service could not parse, so `total` never promises
        # a page that would come back empty.
        total=total - skipped,
        has_more=page.offset + len(rows) < total,
    )


@router.get("/{model_id}", response_model=ModelRead, summary="Get one model")
async def get_model(
    model_id: str,
    models: ModelService = Depends(get_model_service),
) -> ModelRead:
    return ModelRead.model_validate(await models.get(model_id))


@router.patch(
    "/{model_id}",
    response_model=ModelRead,
    summary="Update a model",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def update_model(
    model_id: str,
    payload: ModelUpdate,
    models: ModelService = Depends(get_model_service),
) -> ModelRead:
    return ModelRead.model_validate(await models.update(model_id, payload))


@router.post(
    "/{model_id}/access-request",
    response_model=ModelAccessRequestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ask for a model this deployment does not route",
    description=(
        "Records the request; it does not enable anything. Enabling a model means the "
        "engine has to route it and someone has to accept its cost, so a human does that."
    ),
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def request_model_access(
    model_id: str,
    payload: ModelAccessRequest,
    models: ModelService = Depends(get_model_service),
) -> ModelAccessRequestRead:
    document: dict[str, Any] = await models.request_access(model_id, payload)
    return ModelAccessRequestRead.model_validate(document)

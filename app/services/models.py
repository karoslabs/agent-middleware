"""The model catalog and its access requests.

Same conventions as agents and templates: a model's document id is its
``model_id``, so "one document per model" is enforced by the path rather than
by an application check, and an agent stage storing a ``modelId`` is storing a
reference that either resolves or does not.
"""

from __future__ import annotations

import logging
from typing import Any

from google.api_core.exceptions import AlreadyExists

from app.api.schemas.model import (
    ModelAccessRequest,
    ModelCreate,
    ModelUpdate,
    model_document,
)
from app.core.enums import ModelAvailability
from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.db.firestore import (
    MODEL_ACCESS_REQUESTS,
    MODELS,
    FirestoreDB,
    generate_id,
    snapshot_to_dict,
    utcnow,
)

logger = logging.getLogger(__name__)


class ModelService:
    """Reads and writes the normalized model catalog."""

    def __init__(self, db: FirestoreDB) -> None:
        self._db = db

    async def create(self, payload: ModelCreate) -> dict[str, Any]:
        document = model_document(payload, utcnow())
        try:
            await self._db.document(MODELS, payload.model_id).create(document)
        except AlreadyExists as exc:
            raise ResourceConflictError(f"model '{payload.model_id}' already exists") from exc
        return document

    async def get(self, model_id: str) -> dict[str, Any]:
        snapshot = await self._db.document(MODELS, model_id).get()
        # `snapshot.exists`, not a None check on the flattened dict:
        # `snapshot_to_dict` always returns at least `{"id": ...}`, so a None
        # check silently passes for a document that is not there.
        if not snapshot.exists:
            raise ResourceNotFoundError("model", model_id)
        return snapshot_to_dict(snapshot)

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        availability: ModelAvailability | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Every model, newest-irrelevant: this is a small catalog read whole.

        Filtered in process rather than by query because the collection is
        admin-sized and a Firestore composite index for one optional filter is
        not worth carrying. Returns the total so a caller can page honestly.
        """
        rows: list[dict[str, Any]] = []
        async for snapshot in self._db.collection(MODELS).stream():
            row = snapshot_to_dict(snapshot)
            if availability is not None and row.get("availability") != availability.value:
                continue
            rows.append(row)

        # Stable order the UI can rely on: selectable first, then by name. A
        # dropdown that reorders itself between loads is its own bug.
        order = {
            ModelAvailability.AVAILABLE.value: 0,
            ModelAvailability.NOT_ENABLED.value: 1,
            ModelAvailability.RETIRED.value: 2,
        }
        rows.sort(
            key=lambda r: (
                order.get(str(r.get("availability")), 9),
                str(r.get("display_name", "")),
            )
        )
        return rows[offset : offset + limit], len(rows)

    async def update(self, model_id: str, payload: ModelUpdate) -> dict[str, Any]:
        patch: dict[str, Any] = {
            key: (value.value if hasattr(value, "value") else value)
            for key, value in payload.model_dump(exclude_unset=True).items()
        }
        if not patch:
            return await self.get(model_id)
        await self.get(model_id)  # 404 before write
        patch["updated_at"] = utcnow()
        await self._db.document(MODELS, model_id).update(patch)
        return await self.get(model_id)

    async def request_access(self, model_id: str, payload: ModelAccessRequest) -> dict[str, Any]:
        """Records that someone wants a model this deployment does not route.

        Recorded, never actioned: enabling a model means the engine has to
        route it and someone has to accept its cost, so this captures the ask
        and a human does the enabling. Allowed against any model -- including
        one already available, which is how a duplicate request surfaces as
        data rather than as an error the requester has to interpret.
        """
        model = await self.get(model_id)
        document = {
            "id": generate_id(),
            "model_id": model["model_id"],
            "requested_by": payload.requested_by,
            "reason": payload.reason,
            "agent_id": payload.agent_id,
            "status": "open",
            "created_at": utcnow(),
        }
        await self._db.document(MODEL_ACCESS_REQUESTS, document["id"]).create(document)
        logger.info(
            "model access requested",
            extra={"model_id": model_id, "requested_by": payload.requested_by},
        )
        return document

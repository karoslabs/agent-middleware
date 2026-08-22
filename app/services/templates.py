"""Content templates, their versions, and the agent bindings that select them.

Same conventions as agents and prompts: a template's document id is its slug, a
version's id is its zero-padded number, and an agent-to-template binding's id is
the purpose it serves -- so "one template per purpose per agent" is enforced by
the document path rather than by application checks.
"""

from __future__ import annotations

import logging
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter

from app.api.schemas.template import (
    AgentTemplateLinkCreate,
    TemplateCreate,
    TemplateUpdate,
    TemplateVersionCreate,
)
from app.core.enums import TemplateKind
from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.db.firestore import (
    AGENT_TEMPLATES,
    AGENTS,
    TEMPLATE_VERSIONS,
    TEMPLATES,
    FirestoreDB,
    snapshot_to_dict,
    utcnow,
    version_doc_id,
)

logger = logging.getLogger(__name__)

MAX_VERSION_ALLOCATION_ATTEMPTS = 5
DEFAULT_PURPOSE = "primary"


class TemplateService:
    """Templates, template versions and agent bindings."""

    def __init__(self, db: FirestoreDB) -> None:
        self._db = db

    # --- Templates ---------------------------------------------------------

    async def create(self, payload: TemplateCreate) -> dict[str, Any]:
        """Create a template, plus an initial active version when a body is given."""

        now = utcnow()
        document = {
            "slug": payload.slug,
            "name": payload.name,
            "description": payload.description,
            "kind": payload.kind.value,
            "tags": payload.tags,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }

        try:
            await self._db.document(TEMPLATES, payload.slug).create(document)
        except AlreadyExists as exc:
            raise ResourceConflictError(f"template '{payload.slug}' already exists") from exc

        template = {**document, "id": payload.slug}

        if payload.content is not None or payload.schema_definition is not None:
            await self.create_version(
                payload.slug,
                TemplateVersionCreate(
                    content=payload.content,
                    schema_definition=payload.schema_definition,
                    variables=payload.variables,
                    assets=payload.assets,
                    notes="initial version",
                    activate=True,
                ),
            )

        logger.info("Created template %s", payload.slug)
        return template

    async def get(self, template_ref: str, *, include_deleted: bool = False) -> dict[str, Any]:
        snapshot = await self._db.document(TEMPLATES, template_ref).get()
        if not snapshot.exists:
            raise ResourceNotFoundError("template", template_ref)

        template = snapshot_to_dict(snapshot)
        if template.get("deleted_at") is not None and not include_deleted:
            raise ResourceNotFoundError("template", template_ref)
        return template

    async def get_detail(
        self, template_ref: str, *, include_deleted: bool = False
    ) -> dict[str, Any]:
        """A template with its version history and the active version resolved."""

        template = await self.get(template_ref, include_deleted=include_deleted)
        versions = await self.list_versions(template_ref)
        active = next((version for version in versions if version.get("is_active")), None)
        return {**template, "versions": versions, "active_version": active}

    async def update(self, template_ref: str, payload: TemplateUpdate) -> dict[str, Any]:
        template = await self.get(template_ref)

        patch: dict[str, Any] = {}
        for field, value in payload.model_dump(exclude_unset=True).items():
            patch[field] = value.value if isinstance(value, TemplateKind) else value
        if not patch:
            return template

        patch["updated_at"] = utcnow()
        await self._db.document(TEMPLATES, template_ref).update(patch)
        return {**template, **patch}

    async def soft_delete(self, template_ref: str) -> dict[str, Any]:
        """Mark a template deleted; existing runs keep referencing its versions."""

        template = await self.get(template_ref)
        patch = {"deleted_at": utcnow(), "updated_at": utcnow()}
        await self._db.document(TEMPLATES, template_ref).update(patch)
        return {**template, **patch}

    async def restore(self, template_ref: str) -> dict[str, Any]:
        template = await self.get(template_ref, include_deleted=True)
        if template.get("deleted_at") is None:
            return template
        patch = {"deleted_at": None, "updated_at": utcnow()}
        await self._db.document(TEMPLATES, template_ref).update(patch)
        return {**template, **patch}

    async def list_templates(
        self,
        *,
        kind: TemplateKind | None = None,
        tag: str | None = None,
        query: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List template metadata, newest first (filtered in process)."""

        templates = [
            snapshot_to_dict(snapshot) async for snapshot in self._db.collection(TEMPLATES).stream()
        ]

        needle = query.lower().strip() if query else None
        matches = [
            template
            for template in templates
            if (include_deleted or template.get("deleted_at") is None)
            and (kind is None or template.get("kind") == kind.value)
            and (tag is None or tag in (template.get("tags") or []))
            and (
                needle is None
                or needle in (template.get("slug") or "").lower()
                or needle in (template.get("name") or "").lower()
                or needle in (template.get("description") or "").lower()
            )
        ]
        matches.sort(key=lambda template: template.get("created_at") or utcnow(), reverse=True)
        return matches[offset : offset + limit], len(matches)

    # --- Versions ----------------------------------------------------------

    def _versions(self, template_ref: str) -> Any:
        return self._db.collection(TEMPLATES, template_ref, TEMPLATE_VERSIONS)

    async def create_version(
        self, template_ref: str, payload: TemplateVersionCreate
    ) -> dict[str, Any]:
        await self.get(template_ref)

        for _ in range(MAX_VERSION_ALLOCATION_ATTEMPTS):
            version = await self._next_version(template_ref)
            now = utcnow()
            document = {
                "template_id": template_ref,
                "version": version,
                "content": payload.content,
                "schema_definition": payload.schema_definition,
                "variables": payload.variables,
                "assets": payload.assets,
                "notes": payload.notes,
                "is_active": payload.activate,
                "created_by": payload.created_by,
                "created_at": now,
                "updated_at": now,
            }
            try:
                await self._versions(template_ref).document(version_doc_id(version)).create(
                    document
                )
            except AlreadyExists:
                continue

            if payload.activate:
                await self._deactivate_others(template_ref, keep_version=version)

            logger.info("Created template %s v%s", template_ref, version)
            return {**document, "id": version_doc_id(version)}

        raise ResourceConflictError(
            f"could not allocate a version for template {template_ref!r}; please retry"
        )

    async def _next_version(self, template_ref: str) -> int:
        latest = [
            snapshot_to_dict(snapshot)
            async for snapshot in self._versions(template_ref)
            .order_by("version", direction="DESCENDING")
            .limit(1)
            .stream()
        ]
        return (latest[0]["version"] + 1) if latest else 1

    async def list_versions(self, template_ref: str) -> list[dict[str, Any]]:
        return [
            snapshot_to_dict(snapshot)
            async for snapshot in self._versions(template_ref)
            .order_by("version", direction="DESCENDING")
            .stream()
        ]

    async def get_version(self, template_ref: str, version: int) -> dict[str, Any]:
        snapshot = await self._versions(template_ref).document(version_doc_id(version)).get()
        if not snapshot.exists:
            raise ResourceNotFoundError("template version", f"{template_ref}/v{version}")
        return snapshot_to_dict(snapshot)

    async def find_active_version(self, template_ref: str) -> dict[str, Any] | None:
        active = [
            snapshot_to_dict(snapshot)
            async for snapshot in self._versions(template_ref)
            .where(filter=FieldFilter("is_active", "==", True))
            .stream()
        ]
        if not active:
            return None
        return max(active, key=lambda version: version.get("version", 0))

    async def activate_version(self, template_ref: str, version: int) -> dict[str, Any]:
        template_version = await self.get_version(template_ref, version)
        now = utcnow()
        await self._versions(template_ref).document(version_doc_id(version)).update(
            {"is_active": True, "updated_at": now}
        )
        await self._deactivate_others(template_ref, keep_version=version)
        return {**template_version, "is_active": True, "updated_at": now}

    async def _deactivate_others(self, template_ref: str, *, keep_version: int) -> None:
        now = utcnow()
        async for snapshot in (
            self._versions(template_ref)
            .where(filter=FieldFilter("is_active", "==", True))
            .stream()
        ):
            data = snapshot.to_dict() or {}
            if data.get("version") == keep_version:
                continue
            await snapshot.reference.update({"is_active": False, "updated_at": now})

    # --- Agent bindings ----------------------------------------------------

    def _links(self, agent_id: str) -> Any:
        return self._db.collection(AGENTS, agent_id, AGENT_TEMPLATES)

    async def bind_to_agent(
        self, agent_id: str, purpose: str, payload: AgentTemplateLinkCreate
    ) -> dict[str, Any]:
        """Bind a template to an agent under ``purpose`` (idempotent upsert)."""

        template = await self.get(payload.template_ref)
        now = utcnow()
        document = {
            "agent_id": agent_id,
            "template_id": template["id"],
            "purpose": purpose,
            "is_primary": payload.is_primary,
            "created_at": now,
            "updated_at": now,
        }
        # Rebinding a purpose replaces the previous choice, hence set() not create().
        await self._links(agent_id).document(purpose).set(document)
        return {**document, "id": purpose, "template": template}

    async def list_agent_links(self, agent_id: str) -> list[dict[str, Any]]:
        """Bindings of an agent, each with the bound template's metadata."""

        links = [snapshot_to_dict(snapshot) async for snapshot in self._links(agent_id).stream()]
        for link in links:
            try:
                link["template"] = await self.get(link["template_id"], include_deleted=True)
            except ResourceNotFoundError:
                link["template"] = None
        links.sort(key=lambda link: link.get("purpose") or "")
        return links

    async def get_agent_link(self, agent_id: str, purpose: str) -> dict[str, Any]:
        snapshot = await self._links(agent_id).document(purpose).get()
        if not snapshot.exists:
            raise ResourceNotFoundError("agent template binding", f"{agent_id}/{purpose}")
        return snapshot_to_dict(snapshot)

    async def unbind_from_agent(self, agent_id: str, purpose: str) -> None:
        await self.get_agent_link(agent_id, purpose)
        await self._links(agent_id).document(purpose).delete()

    async def resolve_for_agent(
        self, agent_id: str, *, purpose: str = DEFAULT_PURPOSE, template_ref: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Resolve the template and version a job should use.

        ``template_ref`` overrides the agent's binding, which lets a caller ask
        for a one-off layout without reconfiguring the agent. Returns ``None``
        when the agent has no template for this purpose -- templates are
        optional, so that is not an error.
        """

        if template_ref is None:
            try:
                link = await self.get_agent_link(agent_id, purpose)
            except ResourceNotFoundError:
                return None
            template_ref = link["template_id"]

        template = await self.get(template_ref)
        version = await self.find_active_version(template["id"])
        if version is None:
            raise ResourceConflictError(
                f"template '{template['id']}' has no active version to render"
            )
        return template, version

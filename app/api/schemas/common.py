"""Schema building blocks shared across the control-plane API."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

SlugStr = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
        description=(
            "Stable, URL-safe identifier. Also the Firestore document id, "
            "which is what makes it unique."
        ),
    ),
]


class Page[ItemT](BaseModel):
    """Envelope for every list endpoint.

    ``total`` is only populated for the small, admin-sized collections that are
    filtered in process (agents, templates). Firestore cannot count a filtered
    query cheaply, so high-volume listings (runs, feedback) report ``has_more``
    instead and leave ``total`` null.
    """

    items: list[ItemT]
    limit: int
    offset: int
    has_more: bool = False
    total: int | None = Field(
        default=None, description="Total matches, when the backend can count them cheaply"
    )


class Pagination(BaseModel):
    """Reusable ``limit`` / ``offset`` query parameters."""

    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


def pagination(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    """FastAPI dependency yielding validated pagination parameters."""

    return Pagination(limit=limit, offset=offset)


class OperationResult(BaseModel):
    """Response for operations with no resource body of their own."""

    status: str = "ok"
    detail: str | None = None


def parse_rows[ModelT: BaseModel](
    model: type[ModelT], rows: list[dict[str, Any]], *, collection: str
) -> list[ModelT]:
    """Validate a listing, skipping rows this service cannot parse.

    A list endpoint must not be brought down by one unreadable document. This
    is not hypothetical: prep's Firestore already holds ``agents/`` documents
    written by karosCMO's since-removed in-app agent engine (camelCase
    ``systemPrompt`` / ``outputKind`` / ``runCount``, no ``slug``, no
    ``created_at``). A plain comprehension raised ``ValidationError`` on those
    and turned ``GET /agents`` into a 500 — every legitimate agent invisible
    because two dead rows shared the collection name.

    Fetch-by-id is deliberately left strict: asking for a specific document and
    getting silence would be worse than an error, and nothing else in a listing
    depends on that one row.

    Skipped rows are logged at WARNING with their id, so this degrades loudly
    rather than quietly under-reporting.
    """

    parsed: list[ModelT] = []
    for row in rows:
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            logger.warning(
                "Skipping unparseable %s document %r (%d validation error(s)); it does not "
                "match %s and is most likely owned by another system sharing this database",
                collection,
                row.get("id", "<no id>"),
                exc.error_count(),
                model.__name__,
            )
    return parsed

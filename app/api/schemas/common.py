"""Schema building blocks shared across the control-plane API."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field

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

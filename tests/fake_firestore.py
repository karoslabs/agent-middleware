"""An in-memory stand-in for the async Firestore client.

The test suite needs no emulator, credentials or network: ``FakeFirestoreClient``
implements exactly the surface :mod:`app.db.firestore` and the services use --
document ``get``/``create``/``set``/``update``/``delete`` and queries built from
``where`` / ``order_by`` / ``offset`` / ``limit`` / ``stream``.

Two behaviours are faithful on purpose, because the production code depends on
them: ``create()`` raises ``AlreadyExists`` for a document that exists (this is
how slug and version uniqueness is enforced) and ``update()`` raises
``NotFound`` for one that does not.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from typing import Any

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud.firestore_v1.base_query import FieldFilter

_MISSING = object()


class FakeSnapshot:
    """Mirrors ``DocumentSnapshot`` for the attributes the code reads."""

    def __init__(self, path: str, data: dict[str, Any] | None, reference: FakeDocument) -> None:
        self._path = path
        self._data = data
        self.reference = reference

    @property
    def id(self) -> str:
        return self._path.rsplit("/", 1)[-1]

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._data) if self._data is not None else None


class FakeDocument:
    """Mirrors ``AsyncDocumentReference``."""

    def __init__(self, store: dict[str, dict[str, Any]], path: str) -> None:
        self._store = store
        self._path = path

    @property
    def id(self) -> str:
        return self._path.rsplit("/", 1)[-1]

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self._store, f"{self._path}/{name}")

    async def get(self) -> FakeSnapshot:
        return FakeSnapshot(self._path, self._store.get(self._path), self)

    async def create(self, data: dict[str, Any]) -> None:
        if self._path in self._store:
            raise AlreadyExists(f"document already exists: {self._path}")
        self._store[self._path] = copy.deepcopy(data)

    async def set(self, data: dict[str, Any], merge: bool = False) -> None:
        if merge and self._path in self._store:
            self._store[self._path].update(copy.deepcopy(data))
            return
        self._store[self._path] = copy.deepcopy(data)

    async def update(self, data: dict[str, Any]) -> None:
        if self._path not in self._store:
            raise NotFound(f"no document to update: {self._path}")
        self._store[self._path].update(copy.deepcopy(data))

    async def delete(self) -> None:
        self._store.pop(self._path, None)


class FakeQuery:
    """Mirrors ``AsyncQuery`` for the filters and ordering the services use."""

    def __init__(
        self,
        store: dict[str, dict[str, Any]],
        path: str,
        filters: list[FieldFilter] | None = None,
        order: tuple[str, str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> None:
        self._store = store
        self._path = path
        self._filters = filters or []
        self._order = order
        self._limit = limit
        self._offset = offset

    def _derive(self, **changes: Any) -> FakeQuery:
        state: dict[str, Any] = {
            "filters": self._filters,
            "order": self._order,
            "limit": self._limit,
            "offset": self._offset,
        }
        state.update(changes)
        return FakeQuery(self._store, self._path, **state)

    def where(self, filter: FieldFilter) -> FakeQuery:  # noqa: A002 - matches the real API
        return self._derive(filters=[*self._filters, filter])

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> FakeQuery:
        return self._derive(order=(field_path, direction))

    def limit(self, count: int) -> FakeQuery:
        return self._derive(limit=count)

    def offset(self, count: int) -> FakeQuery:
        return self._derive(offset=count)

    async def stream(self) -> AsyncIterator[FakeSnapshot]:
        for path, data in self._matching_documents():
            yield FakeSnapshot(path, data, FakeDocument(self._store, path))

    def _matching_documents(self) -> list[tuple[str, dict[str, Any]]]:
        depth = self._path.count("/") + 2
        documents = [
            (path, data)
            for path, data in self._store.items()
            if path.startswith(f"{self._path}/") and path.count("/") + 1 == depth
        ]
        documents = [
            (path, data) for path, data in documents if self._passes_filters(data)
        ]

        if self._order is not None:
            field, direction = self._order
            documents.sort(
                key=lambda item: _sort_key(item[1].get(field)),
                reverse=direction == "DESCENDING",
            )
        else:
            documents.sort(key=lambda item: item[0])

        documents = documents[self._offset :]
        if self._limit is not None:
            documents = documents[: self._limit]
        return documents

    def _passes_filters(self, data: dict[str, Any]) -> bool:
        return all(_matches(data.get(f.field_path, _MISSING), f) for f in self._filters)


class FakeCollection(FakeQuery):
    """Mirrors ``AsyncCollectionReference``: a query that can also address documents."""

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self._store, f"{self._path}/{document_id}")


class FakeFirestoreClient:
    """Mirrors ``AsyncClient``. ``documents`` is exposed for assertions."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def collection(self, path: str) -> FakeCollection:
        return FakeCollection(self.documents, path)

    def document(self, path: str) -> FakeDocument:
        return FakeDocument(self.documents, path)

    def close(self) -> None:
        return None


def _matches(value: Any, field_filter: FieldFilter) -> bool:
    if value is _MISSING:
        return False

    expected = field_filter.value
    operator = field_filter.op_string
    if operator == "==":
        return bool(value == expected)
    if operator == "!=":
        return bool(value != expected)
    if operator == ">=":
        return bool(value >= expected)
    if operator == ">":
        return bool(value > expected)
    if operator == "<=":
        return bool(value <= expected)
    if operator == "<":
        return bool(value < expected)
    if operator == "in":
        return value in expected
    if operator == "array_contains":
        return expected in (value or [])
    raise NotImplementedError(f"operator {operator!r} is not supported by the fake")


def _sort_key(value: Any) -> tuple[int, Any]:
    """Sort ``None`` first, like Firestore does, without comparing mixed types."""

    return (0, "") if value is None else (1, value)

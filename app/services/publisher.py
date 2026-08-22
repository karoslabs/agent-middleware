"""Async-friendly wrapper around the Google Cloud Pub/Sub publisher client."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Executor
from functools import partial

# `google.cloud` is a namespace package whose submodules mypy cannot see as
# attributes, even though this is the import form the library documents. The
# ignore is scoped to this one line rather than silenced repo-wide so a real
# attribute error elsewhere still surfaces.
from google.cloud import pubsub_v1  # type: ignore[attr-defined]

from app.config import Settings
from app.core.exceptions import MessagePublishError

logger = logging.getLogger(__name__)


class PublisherService:
    """Publishes messages to a configured topic.

    The underlying ``PublisherClient`` is synchronous (it returns
    ``concurrent.futures.Future`` objects), so calls are offloaded to a
    thread-pool executor to avoid blocking the asyncio event loop.
    """

    def __init__(self, settings: Settings, client: pubsub_v1.PublisherClient | None = None) -> None:
        self._settings = settings
        self._client = client or pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(
            settings.gcp_project_id, settings.job_topic_id
        )

    @property
    def topic_path(self) -> str:
        """Path of the job topic — the only topic this service publishes to."""

        return self._topic_path

    def topic_path_for(self, topic_id: str | None) -> str:
        """Resolve a topic id to a full path, defaulting to the job topic."""

        if topic_id is None:
            return self._topic_path
        return self._client.topic_path(self._settings.gcp_project_id, topic_id)

    def publish_sync(
        self,
        data: bytes,
        attributes: dict[str, str] | None = None,
        *,
        topic_id: str | None = None,
    ) -> str:
        """Publish a message and block until the broker acknowledges it.

        Intended for use from non-asyncio contexts, such as the Pub/Sub
        streaming-pull callback thread.
        """

        topic_path = self.topic_path_for(topic_id)
        try:
            future = self._client.publish(topic_path, data=data, **(attributes or {}))
            return future.result(timeout=self._settings.publish_timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - normalize all publish failures into one type
            logger.exception("Failed to publish message to %s", topic_path)
            raise MessagePublishError(topic_path, exc) from exc

    async def publish_async(
        self,
        data: bytes,
        attributes: dict[str, str] | None = None,
        *,
        topic_id: str | None = None,
        executor: Executor | None = None,
    ) -> str:
        """Publish a message without blocking the event loop."""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            executor, partial(self.publish_sync, data, attributes, topic_id=topic_id)
        )

    def close(self) -> None:
        transport = getattr(self._client, "transport", None)
        close = getattr(transport, "close", None)
        if callable(close):
            close()

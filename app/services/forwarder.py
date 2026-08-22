"""Shared forwarding logic used by both the pull subscriber and the push route."""

from __future__ import annotations

import logging

from app.services.publisher import PublisherService

logger = logging.getLogger(__name__)


class MessageForwarder:
    """Republishes an inbound message onto the configured destination topic.

    Every attribute of the original message is preserved, and the id of the
    source message is stamped as ``forwarded_from_message_id`` so the flow
    can be traced end to end.
    """

    def __init__(self, publisher: PublisherService) -> None:
        self._publisher = publisher

    def forward_sync(
        self,
        data: bytes,
        attributes: dict[str, str] | None = None,
        *,
        source_message_id: str | None = None,
    ) -> str:
        forwarded_attributes = dict(attributes or {})
        if source_message_id:
            forwarded_attributes["forwarded_from_message_id"] = source_message_id

        message_id = self._publisher.publish_sync(data, forwarded_attributes)
        logger.info(
            "Forwarded message (source_id=%s) to %s as %s",
            source_message_id,
            self._publisher.topic_path,
            message_id,
        )
        return message_id

    async def forward_async(
        self,
        data: bytes,
        attributes: dict[str, str] | None = None,
        *,
        source_message_id: str | None = None,
    ) -> str:
        forwarded_attributes = dict(attributes or {})
        if source_message_id:
            forwarded_attributes["forwarded_from_message_id"] = source_message_id

        message_id = await self._publisher.publish_async(data, forwarded_attributes)
        logger.info(
            "Forwarded message (source_id=%s) to %s as %s",
            source_message_id,
            self._publisher.topic_path,
            message_id,
        )
        return message_id

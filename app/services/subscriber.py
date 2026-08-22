"""Background pull subscriber that continuously forwards Pub/Sub messages."""

from __future__ import annotations

import logging

from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.subscriber.futures import StreamingPullFuture
from google.cloud.pubsub_v1.subscriber.message import Message
from google.cloud.pubsub_v1.types import FlowControl

from app.config import Settings
from app.core.exceptions import MessagePublishError
from app.services.forwarder import MessageForwarder

logger = logging.getLogger(__name__)


class PubSubSubscriber:
    """Wraps a Pub/Sub streaming-pull subscription.

    The Google client library manages its own background threads for the
    streaming pull; this class only owns the lifecycle (start/stop) and the
    per-message callback that forwards each message and acks/nacks it.
    """

    def __init__(
        self,
        settings: Settings,
        forwarder: MessageForwarder,
        client: pubsub_v1.SubscriberClient | None = None,
    ) -> None:
        self._settings = settings
        self._forwarder = forwarder
        self._client = client or pubsub_v1.SubscriberClient()
        self._subscription_path = self._client.subscription_path(
            settings.gcp_project_id, settings.pubsub_source_subscription_id
        )
        self._streaming_pull_future: StreamingPullFuture | None = None

    @property
    def subscription_path(self) -> str:
        return self._subscription_path

    @property
    def is_running(self) -> bool:
        return self._streaming_pull_future is not None and not self._streaming_pull_future.done()

    def start(self) -> None:
        """Start listening for messages. Non-blocking."""

        if self.is_running:
            logger.warning("Subscriber for %s is already running", self._subscription_path)
            return

        flow_control = FlowControl(max_messages=self._settings.subscriber_max_messages)
        self._streaming_pull_future = self._client.subscribe(
            self._subscription_path,
            callback=self._handle_message,
            flow_control=flow_control,
        )
        logger.info("Started pull subscriber on %s", self._subscription_path)

    def stop(self, timeout: float = 30.0) -> None:
        """Cancel the streaming pull and wait for graceful shutdown."""

        if self._streaming_pull_future is None:
            return

        self._streaming_pull_future.cancel()
        try:
            self._streaming_pull_future.result(timeout=timeout)
        except Exception:  # noqa: BLE001 - shutdown must never raise
            logger.info("Pull subscriber on %s stopped", self._subscription_path)
        finally:
            self._streaming_pull_future = None
            self._client.close()

    def _handle_message(self, message: Message) -> None:
        try:
            self._forwarder.forward_sync(
                data=message.data,
                attributes=dict(message.attributes),
                source_message_id=message.message_id,
            )
            message.ack()
        except MessagePublishError:
            logger.exception(
                "Nacking message %s from %s after forwarding failure",
                message.message_id,
                self._subscription_path,
            )
            message.nack()
        except Exception:  # noqa: BLE001 - never let the callback thread die
            logger.exception(
                "Unexpected error handling message %s from %s",
                message.message_id,
                self._subscription_path,
            )
            message.nack()

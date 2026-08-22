"""Pydantic schemas for the Pub/Sub push endpoint and API responses."""

from __future__ import annotations

import base64
import binascii

from pydantic import BaseModel, Field

from app.core.exceptions import InvalidPushMessageError


class PubSubPushMessage(BaseModel):
    """The ``message`` object inside a Pub/Sub push envelope."""

    data: str | None = Field(
        default=None, description="Base64-encoded message payload"
    )
    attributes: dict[str, str] = Field(default_factory=dict)
    message_id: str = Field(alias="messageId")
    publish_time: str | None = Field(default=None, alias="publishTime")

    model_config = {"populate_by_name": True}

    def decoded_data(self) -> bytes:
        if not self.data:
            return b""
        try:
            return base64.b64decode(self.data)
        except (binascii.Error, ValueError) as exc:
            raise InvalidPushMessageError("message.data is not valid base64") from exc


class PubSubPushEnvelope(BaseModel):
    """Body sent by Google Cloud Pub/Sub to a push subscription endpoint."""

    message: PubSubPushMessage
    subscription: str


class ForwardResult(BaseModel):
    """Response returned once a message has been forwarded successfully."""

    forwarded_message_id: str
    source_message_id: str | None = None

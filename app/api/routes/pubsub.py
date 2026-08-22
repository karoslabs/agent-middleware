"""Route that receives Pub/Sub push messages and forwards them to another topic."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status

from app.api.schemas.pubsub import ForwardResult, PubSubPushEnvelope
from app.dependencies import get_forwarder
from app.services.forwarder import MessageForwarder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pubsub", tags=["pubsub"])


@router.post(
    "/push",
    response_model=ForwardResult,
    status_code=status.HTTP_200_OK,
    summary="Pub/Sub push endpoint",
    description=(
        "Compatible with a Google Cloud Pub/Sub push subscription. Every "
        "message delivered here is decoded and forwarded, unchanged, to the "
        "configured destination topic."
    ),
)
async def receive_push_message(
    envelope: PubSubPushEnvelope,
    forwarder: MessageForwarder = Depends(get_forwarder),
) -> ForwardResult:
    message = envelope.message
    data = message.decoded_data()

    forwarded_message_id = await forwarder.forward_async(
        data=data,
        attributes=message.attributes,
        source_message_id=message.message_id,
    )

    return ForwardResult(
        forwarded_message_id=forwarded_message_id,
        source_message_id=message.message_id,
    )

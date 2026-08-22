from app.services.forwarder import MessageForwarder
from app.services.publisher import PublisherService
from tests.conftest import FakePublisherClient


def test_forward_sync_publishes_with_source_attribute(
    publisher_service: PublisherService, fake_publisher_client: FakePublisherClient
) -> None:
    forwarder = MessageForwarder(publisher_service)

    message_id = forwarder.forward_sync(
        data=b"payload",
        attributes={"a": "1"},
        source_message_id="source-1",
    )

    assert message_id == "1"
    _, data, attributes = fake_publisher_client.published[0]
    assert data == b"payload"
    assert attributes == {"a": "1", "forwarded_from_message_id": "source-1"}


async def test_forward_async_publishes(
    publisher_service: PublisherService, fake_publisher_client: FakePublisherClient
) -> None:
    forwarder = MessageForwarder(publisher_service)

    message_id = await forwarder.forward_async(data=b"async-payload", source_message_id="source-2")

    assert message_id == "1"
    _, data, attributes = fake_publisher_client.published[0]
    assert data == b"async-payload"
    assert attributes == {"forwarded_from_message_id": "source-2"}

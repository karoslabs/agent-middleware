from fastapi.testclient import TestClient

from tests.conftest import FakePublisherClient, encode_data


def test_push_message_is_forwarded(
    client: TestClient, fake_publisher_client: FakePublisherClient
) -> None:
    body = {
        "message": {
            "data": encode_data("hello world"),
            "attributes": {"foo": "bar"},
            "messageId": "12345",
            "publishTime": "2024-01-01T00:00:00Z",
        },
        "subscription": "projects/test-project/subscriptions/source-subscription",
    }

    response = client.post("/pubsub/push", json=body)

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_message_id"] == "12345"
    assert payload["forwarded_message_id"]

    assert len(fake_publisher_client.published) == 1
    topic, data, attributes = fake_publisher_client.published[0]
    assert topic == "projects/test-project/topics/test-topic"
    assert data == b"hello world"
    assert attributes["foo"] == "bar"
    assert attributes["forwarded_from_message_id"] == "12345"


def test_push_message_with_empty_data(client: TestClient) -> None:
    body = {
        "message": {
            "data": None,
            "attributes": {},
            "messageId": "1",
        },
        "subscription": "projects/test-project/subscriptions/source-subscription",
    }

    response = client.post("/pubsub/push", json=body)

    assert response.status_code == 200


def test_push_message_with_invalid_base64_returns_400(client: TestClient) -> None:
    body = {
        "message": {
            "data": "not-valid-base64!!",
            "attributes": {},
            "messageId": "2",
        },
        "subscription": "projects/test-project/subscriptions/source-subscription",
    }

    response = client.post("/pubsub/push", json=body)

    assert response.status_code == 400

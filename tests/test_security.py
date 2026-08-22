"""Service-to-service authentication.

The OIDC path is exercised with ``_verify_oidc_token`` patched out: the thing
worth testing here is our own policy (is an audience configured, is the caller
on the allowlist, does a bad token become a 401), not Google's signature
verification, which would need network and real keys to reach.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security
from app.config import Settings
from app.db.firestore import FirestoreDB
from app.main import build_services, create_app
from app.services.publisher import PublisherService
from tests.conftest import FakePublisherClient
from tests.fake_firestore import FakeFirestoreClient


def _client_with(settings: Settings) -> Iterator[TestClient]:
    database = FirestoreDB(settings, client=FakeFirestoreClient())  # type: ignore[arg-type]
    publisher = PublisherService(settings, client=FakePublisherClient())  # type: ignore[arg-type]

    app = create_app()

    @asynccontextmanager
    async def lifespan(inner: FastAPI):  # type: ignore[no-untyped-def]
        build_services(inner, settings, database, publisher=publisher)
        yield

    app.router.lifespan_context = lifespan
    with TestClient(app) as test_client:
        yield test_client


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "gcp_project_id": "test-project",
        "pubsub_job_topic_id": "test-jobs-topic",
        "auth_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


# --- Health stays open ------------------------------------------------------


def test_health_is_reachable_without_a_token() -> None:
    """Cloud Run's probes carry no identity token; gating health breaks deploys."""

    settings = _settings(auth_audience="https://mw.example.run.app")
    for client in _client_with(settings):
        assert client.get("/health/live").status_code == 200


# --- Missing / malformed credentials ---------------------------------------


def test_protected_route_rejects_a_missing_token() -> None:
    settings = _settings(auth_audience="https://mw.example.run.app")
    for client in _client_with(settings):
        response = client.get("/agents")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_protected_route_rejects_an_invalid_oidc_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(token: str, audience: str) -> dict[str, Any]:
        raise ValueError("Token expired")

    monkeypatch.setattr(security, "_verify_oidc_token", boom)

    settings = _settings(auth_audience="https://mw.example.run.app")
    for client in _client_with(settings):
        response = client.get("/agents", headers={"Authorization": "Bearer not-a-real-token"})
        assert response.status_code == 401


# --- The audience is mandatory ---------------------------------------------


def test_missing_audience_is_a_500_not_an_open_door(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an audience a token cannot be bound to this service.

    Google issues valid tokens to every account on every project, so verifying
    signature alone would accept essentially anything. Refusing loudly is the
    only safe direction; the regression this guards against is somebody
    "fixing" the misconfiguration by passing audience=None.
    """

    def should_not_run(token: str, audience: str) -> dict[str, Any]:
        raise AssertionError("verification must not be attempted without an audience")

    monkeypatch.setattr(security, "_verify_oidc_token", should_not_run)

    settings = _settings(auth_audience=None)
    for client in _client_with(settings):
        response = client.get("/agents", headers={"Authorization": "Bearer anything"})
        assert response.status_code == 500


# --- A verified caller -------------------------------------------------------


def test_a_verified_token_is_allowed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def verify(token: str, audience: str) -> dict[str, Any]:
        seen["token"] = token
        seen["audience"] = audience
        return {"sub": "1234", "email": "portal@karoscmo.iam.gserviceaccount.com"}

    monkeypatch.setattr(security, "_verify_oidc_token", verify)

    settings = _settings(auth_audience="https://mw.example.run.app")
    for client in _client_with(settings):
        response = client.get("/agents", headers={"Authorization": "Bearer good-token"})
        assert response.status_code == 200, response.text

    assert seen["token"] == "good-token"
    # The configured audience must actually reach the verifier.
    assert seen["audience"] == "https://mw.example.run.app"


def test_allowlist_rejects_an_unlisted_service_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        security,
        "_verify_oidc_token",
        lambda token, audience: {"sub": "1", "email": "stranger@evil.iam.gserviceaccount.com"},
    )

    settings = _settings(
        auth_audience="https://mw.example.run.app",
        auth_allowed_service_accounts=["portal@karoscmo.iam.gserviceaccount.com"],
    )
    for client in _client_with(settings):
        response = client.get("/agents", headers={"Authorization": "Bearer good-signature"})
        # 403, not 401: the token is genuine, the caller just isn't permitted.
        assert response.status_code == 403


def test_allowlist_admits_a_listed_service_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        security,
        "_verify_oidc_token",
        lambda token, audience: {"sub": "1", "email": "portal@karoscmo.iam.gserviceaccount.com"},
    )

    settings = _settings(
        auth_audience="https://mw.example.run.app",
        auth_allowed_service_accounts=["portal@karoscmo.iam.gserviceaccount.com"],
    )
    for client in _client_with(settings):
        assert client.get("/agents", headers={"Authorization": "Bearer ok"}).status_code == 200


# --- The development bearer token -------------------------------------------


def test_dev_token_is_accepted_outside_production() -> None:
    settings = _settings(environment="local", auth_dev_token="s3cret", auth_audience=None)
    for client in _client_with(settings):
        assert client.get("/agents", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_dev_token_is_ignored_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stray AUTH_DEV_TOKEN on a production deploy must not be a bypass."""

    def reject(token: str, audience: str) -> dict[str, Any]:
        raise ValueError("not a real OIDC token")

    monkeypatch.setattr(security, "_verify_oidc_token", reject)

    settings = _settings(
        environment="production",
        auth_dev_token="s3cret",
        auth_audience="https://mw.example.run.app",
    )
    for client in _client_with(settings):
        # Presented as a bearer token it is no longer special: it falls through
        # to OIDC verification, which rejects it.
        response = client.get("/agents", headers={"Authorization": "Bearer s3cret"})
        assert response.status_code == 401


def test_a_wrong_dev_token_still_falls_through_to_oidc(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dev token being configured must not shadow real OIDC callers."""

    monkeypatch.setattr(
        security,
        "_verify_oidc_token",
        lambda token, audience: {"sub": "9", "email": "real@karoscmo.iam.gserviceaccount.com"},
    )

    settings = _settings(
        environment="local",
        auth_dev_token="s3cret",
        auth_audience="https://mw.example.run.app",
    )
    for client in _client_with(settings):
        response = client.get("/agents", headers={"Authorization": "Bearer a-real-oidc-token"})
        assert response.status_code == 200


# --- The escape hatch --------------------------------------------------------


def test_auth_can_be_disabled_entirely_for_local_development() -> None:
    settings = _settings(auth_enabled=False)
    for client in _client_with(settings):
        assert client.get("/agents").status_code == 200

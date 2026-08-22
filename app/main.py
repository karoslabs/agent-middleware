"""FastAPI application entrypoint: wiring, lifespan management, exception handling.

The service plays two roles:

* **Control plane / data hub** -- the source of truth in Firestore for agents,
  versioned system prompts, few-shot examples, content templates, runs and
  feedback. The portal reads a resolved context from here when launching a task.
* **Pub/Sub bridge** -- job payloads are published to the engine topic, and the
  pull subscriber plus ``POST /pubsub/push`` forward inbound messages on.

The engine itself is a stateless worker: it receives everything it needs inside
the message and never reads this database.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api.routes import agents, context, health, prompts, pubsub, runs, templates
from app.config import Settings, get_settings
from app.core.exceptions import (
    IncompleteAgentConfigurationError,
    InvalidPushMessageError,
    InvalidStateError,
    MessagePublishError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.db.firestore import FirestoreDB
from app.logging_config import configure_logging
from app.services.agents import AgentService
from app.services.context import ContextService
from app.services.dispatch import DispatchService
from app.services.feedback import FeedbackService
from app.services.forwarder import MessageForwarder
from app.services.prompts import PromptService
from app.services.publisher import PublisherService
from app.services.runs import RunService
from app.services.subscriber import PubSubSubscriber
from app.services.templates import TemplateService

logger = logging.getLogger(__name__)


def build_services(
    app: FastAPI,
    settings: Settings,
    database: FirestoreDB,
    publisher: PublisherService | None = None,
) -> None:
    """Construct every service once and attach it to ``app.state``.

    Request handlers reach these through ``app.dependencies``, so no handler ever
    builds a Firestore or Pub/Sub client of its own. ``publisher`` is injectable
    so tests can wire a fake Pub/Sub client without patching module globals.
    """

    publisher = publisher or PublisherService(settings)
    agent_service = AgentService(database)
    prompt_service = PromptService(database)
    template_service = TemplateService(database)
    run_service = RunService(database)
    context_service = ContextService(settings, agent_service, prompt_service, template_service)

    app.state.settings = settings
    app.state.db = database
    app.state.publisher = publisher
    app.state.forwarder = MessageForwarder(publisher)
    app.state.agent_service = agent_service
    app.state.prompt_service = prompt_service
    app.state.template_service = template_service
    app.state.run_service = run_service
    app.state.feedback_service = FeedbackService(database, run_service, prompt_service)
    app.state.context_service = context_service
    app.state.dispatch_service = DispatchService(
        settings, context_service, run_service, publisher
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings.log_level)

    database = FirestoreDB(settings)
    build_services(app, settings, database)

    subscriber = PubSubSubscriber(settings, app.state.forwarder)
    app.state.subscriber = subscriber
    if settings.enable_pull_subscriber:
        subscriber.start()

    logger.info(
        "%s started (environment=%s, firestore=%s/%s, job_topic=%s)",
        settings.app_name,
        settings.environment,
        settings.resolved_firestore_project_id,
        settings.firestore_database,
        settings.job_topic_id,
    )
    try:
        yield
    finally:
        logger.info("Shutting down %s", settings.app_name)
        subscriber.stop()
        app.state.publisher.close()
        database.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Middleware",
        description=(
            "Control plane and data hub for the agent platform: agents, versioned "
            "system prompts, few-shot examples, content templates, run history and "
            "the feedback store -- plus the Pub/Sub bridge that hands jobs to the "
            "engine."
        ),
        version="0.2.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(agents.router)
    app.include_router(prompts.router)
    app.include_router(templates.router)
    app.include_router(templates.agent_router)
    app.include_router(context.router)
    app.include_router(runs.router)
    app.include_router(pubsub.router)

    register_exception_handlers(app)
    return app


def register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions onto HTTP responses, once, in one place."""

    @app.exception_handler(ResourceNotFoundError)
    async def handle_not_found(_: Request, exc: ResourceNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)}
        )

    @app.exception_handler(ResourceConflictError)
    async def handle_conflict(_: Request, exc: ResourceConflictError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    @app.exception_handler(InvalidStateError)
    async def handle_invalid_state(_: Request, exc: InvalidStateError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})

    @app.exception_handler(IncompleteAgentConfigurationError)
    async def handle_incomplete_agent(
        _: Request, exc: IncompleteAgentConfigurationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)}
        )

    @app.exception_handler(MessagePublishError)
    async def handle_publish_error(_: Request, exc: MessagePublishError) -> JSONResponse:
        logger.error("Publish error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "Failed to publish message to Pub/Sub."},
        )

    @app.exception_handler(InvalidPushMessageError)
    async def handle_invalid_push(_: Request, exc: InvalidPushMessageError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc)},
        )


app = create_app()

"""FastAPI dependency providers.

Services are constructed once during application startup and stored on
``app.state``; these dependencies just hand them to request handlers, so a
handler never builds a Firestore or Pub/Sub client of its own.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from app.config import Settings
from app.db.firestore import FirestoreDB
from app.services.agents import AgentService
from app.services.context import ContextService
from app.services.dispatch import DispatchService
from app.services.engine_prompts import EnginePromptService
from app.services.feedback import FeedbackService
from app.services.models import ModelService
from app.services.prompts import PromptService
from app.services.runs import RunService
from app.services.templates import TemplateService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> FirestoreDB:
    return request.app.state.db


def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


def get_prompt_service(request: Request) -> PromptService:
    return request.app.state.prompt_service


def get_engine_prompt_service(request: Request) -> EnginePromptService:
    return request.app.state.engine_prompt_service


def get_template_service(request: Request) -> TemplateService:
    return request.app.state.template_service


def get_model_service(request: Request) -> ModelService:
    return request.app.state.model_service


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_feedback_service(request: Request) -> FeedbackService:
    return request.app.state.feedback_service


def get_context_service(request: Request) -> ContextService:
    return request.app.state.context_service


def get_dispatch_service(request: Request) -> DispatchService:
    return request.app.state.dispatch_service


async def resolve_agent(
    agent_id: str, agents: AgentService = Depends(get_agent_service)
) -> dict[str, Any]:
    """Load the agent named in the path, 404-ing before any nested work happens.

    Used by every nested route (prompts, examples, runs, feedback) so they never
    write into a subcollection of an agent that does not exist.
    """

    return await agents.get(agent_id)

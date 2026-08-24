"""The prompt store agent-engine executes from.

Distinct from ``prompts.py``, which serves this service's own
``agents/{slug}/prompts`` subcollection. That one is append-only and versioned
because a run must be traceable to the exact text it used. This one is neither,
and the difference is not a lapse: a stage's ``skillRef`` pins a version in
compiled TypeScript, so the only write that changes what an agent runs is one
that replaces the content of the version already named. See
``app/services/engine_prompts.py`` for the full reasoning and for where the
superseded text goes.

Addressed by prompt id and version rather than by the ``id@version`` skillRef,
so no ``@`` ever has to survive a URL.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.schemas.engine_prompt import (
    EnginePromptRead,
    EnginePromptUpdate,
    EnginePromptVersionSummary,
)
from app.dependencies import get_engine_prompt_service
from app.services.engine_prompts import EnginePromptService

router = APIRouter(prefix="/engine-prompts", tags=["engine prompts"])


@router.get(
    "/{prompt_id}/versions/{version}",
    response_model=EnginePromptRead,
    summary="Read the prompt text a stage will execute",
    description=(
        "Resolved exactly the way agent-engine's own FirestorePromptStore resolves it, "
        "so what this returns is what a run would load. Reading it any other way risks an "
        "editor that shows one prompt while the agent executes another."
    ),
)
async def read_version(
    prompt_id: str,
    version: str,
    prompts: EnginePromptService = Depends(get_engine_prompt_service),
) -> EnginePromptRead:
    return EnginePromptRead.model_validate(await prompts.read(f"{prompt_id}@{version}"))


@router.get(
    "/{prompt_id}",
    response_model=EnginePromptRead,
    summary="Read a prompt's latest version",
    description="Falls back to the prompt's own `latestVersion`, as an unpinned skillRef does.",
)
async def read_latest(
    prompt_id: str,
    prompts: EnginePromptService = Depends(get_engine_prompt_service),
) -> EnginePromptRead:
    return EnginePromptRead.model_validate(await prompts.read(prompt_id))


@router.put(
    "/{prompt_id}/versions/{version}",
    response_model=EnginePromptRead,
    status_code=status.HTTP_200_OK,
    summary="Replace the prompt text a stage executes",
    description=(
        "Updates this version in place, which is the only write that takes effect: a stage's "
        "skillRef names one version, so a new version would be inert until someone changed "
        "TypeScript. The superseded text is kept on the prompt document. Empty content is "
        "refused — a stage with no system prompt still runs, on nothing but its turn contract."
    ),
)
async def replace_version(
    prompt_id: str,
    version: str,
    payload: EnginePromptUpdate,
    actor: Annotated[str | None, Query(description="Who is saving, for the audit trail")] = None,
    prompts: EnginePromptService = Depends(get_engine_prompt_service),
) -> EnginePromptRead:
    updated = await prompts.write(f"{prompt_id}@{version}", payload.content, actor)
    return EnginePromptRead.model_validate(updated)


@router.get(
    "/{prompt_id}/history",
    response_model=list[EnginePromptVersionSummary],
    summary="Superseded revisions of a prompt, oldest first",
)
async def read_history(
    prompt_id: str,
    prompts: EnginePromptService = Depends(get_engine_prompt_service),
) -> list[Any]:
    return [
        EnginePromptVersionSummary.model_validate(row) for row in await prompts.history(prompt_id)
    ]

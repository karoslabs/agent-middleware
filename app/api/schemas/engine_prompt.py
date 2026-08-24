"""Wire shapes for the prompt store agent-engine executes from."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EnginePromptRead(BaseModel):
    """One prompt version, as a stage would load it."""

    prompt_id: str
    version: str
    #: `promptId@version` — the exact string a stage's `skillRef` carries.
    skill_ref: str
    content: str
    #: True when the caller named a version rather than relying on `latestVersion`.
    #: Every compiled stage pins one, so this is normally true; it is surfaced
    #: because an unpinned read can move under you and a pinned one cannot.
    pinned: bool = True
    updated_at: Any | None = None
    updated_by: str | None = None


class EnginePromptUpdate(BaseModel):
    """Body for ``PUT /engine-prompts/{prompt_id}/versions/{version}``."""

    #: Refused when blank. A stage with no system prompt does not fail — it runs
    #: on its bare turn contract and produces plausible, unmoored output — so an
    #: empty save is the one edit that must not be allowed to look like success.
    content: str = Field(min_length=1)


class EnginePromptVersionSummary(BaseModel):
    """One superseded revision, kept so a bad edit can be read back."""

    version: str
    content: str
    replaced_at: Any | None = None
    replaced_by: str | None = None

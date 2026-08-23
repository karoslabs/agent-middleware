"""How an agent presents itself in the portal catalog and Agent Studio.

These fields exist because the portal had nowhere to read them from. An agent
lived in the control plane with a prompt and a template binding, and the
catalog still had to invent an icon, a category and a price — or omit the agent
entirely, which is what it did.

They are first-class fields rather than keys inside ``config`` for one reason:
``config`` is opaque to this service and is passed through to the engine, so
anything in it is a private arrangement between an agent and its workflow. What
the catalog renders is a public contract, and a schema is how a contract gets
enforced instead of remembered.

``stages`` is the one to read carefully. For the eleven hand-written
agent-engine workflows the stages are TypeScript, not data: they are recorded
here so the Studio can SHOW what an agent does, and they are documented as
read-only because editing this list would change a page and not a program.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentStage(BaseModel):
    """One step of an agent's workflow, for display.

    Mirrors the workflow's real step id so the Studio and a run's step trace
    line up — a reader comparing the two is the whole point of showing them.
    """

    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=255)
    description: str | None = None
    #: A gate pauses for a human. Worth showing, because it is the difference
    #: between an agent that finishes on its own and one that waits.
    is_gate: bool = False


class AgentInputDef(BaseModel):
    """One field the run dialog asks for before dispatching.

    Deliberately the same vocabulary as karosCMO's ``DynamicAgentInputDef``
    (key/type/label/helpText/required/placeholder/options), so the portal can
    render these with the control it already has rather than a second one that
    drifts.
    """

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    type: str = Field(default="text", max_length=32)
    label: str = Field(min_length=1, max_length=255)
    help_text: str | None = None
    required: bool = False
    placeholder: str | None = None
    options: list[str] = Field(default_factory=list)


class AgentPresentation(BaseModel):
    """The catalog/Studio half of an agent record."""

    #: lucide icon name, matching karosCMO's own icon component.
    icon: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    #: Credits charged per run. Null means "use the platform default" rather
    #: than "free" — a zero here would be a priced decision, and absent is not.
    credit_cost: int | None = Field(default=None, ge=0)
    #: Whether the agent appears in client-facing surfaces at all.
    is_public: bool = True
    required_inputs: list[AgentInputDef] = Field(default_factory=list)
    #: Read-only for hand-written workflows: their stages are code.
    stages: list[AgentStage] = Field(default_factory=list)
    #: True when `stages` describes compiled code rather than editable data.
    stages_read_only: bool = True

    def as_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

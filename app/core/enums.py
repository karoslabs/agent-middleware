"""Enumerations shared by the ORM models and the API schemas.

Values are stored in the database as plain strings, which keeps migrations
simple (no native database enum types to alter) while still giving the API a
closed, documented set of values.
"""

from __future__ import annotations

from enum import StrEnum


class AgentStatus(StrEnum):
    """Lifecycle status of an agent, controlled by the portal."""

    ACTIVE = "active"
    DISABLED = "disabled"


class TemplateKind(StrEnum):
    """What a content template describes."""

    HTML_LAYOUT = "html_layout"
    JSON_SCHEMA = "json_schema"
    POST = "post"
    LANDING_PAGE = "landing_page"
    EMAIL = "email"
    OTHER = "other"


class ExampleSource(StrEnum):
    """Where a few-shot example came from."""

    MANUAL = "manual"
    FEEDBACK = "feedback"


class RunStatus(StrEnum):
    """Lifecycle of a single agent run (one job handed to the engine)."""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class FeedbackStatus(StrEnum):
    """Reviewer verdict attached to a run."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"

class ModelVendor(StrEnum):
    """Who serves a model. Distinct from where it runs: Claude on Vertex is
    still Anthropic's model, and the engine's router cares about both."""

    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    META = "meta"
    OTHER = "other"


class ModelAvailability(StrEnum):
    """Whether a Studio author may select this model.

    ``not_enabled`` is the interesting one: Vertex offers it, this deployment
    does not route it. Listed and shown disabled rather than hidden, because a
    catalog that silently omits models reads as "this is everything Vertex
    has", and someone concludes a model is unavailable when it is one config
    change away.
    """

    AVAILABLE = "available"
    NOT_ENABLED = "not_enabled"
    RETIRED = "retired"

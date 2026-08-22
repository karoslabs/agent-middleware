"""Application configuration, loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    All values can be overridden via environment variables (or a local .env
    file). Google Cloud credentials are resolved by the underlying client
    libraries via the standard ``GOOGLE_APPLICATION_CREDENTIALS`` mechanism.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "agent-middleware"
    environment: str = Field(default="local", description="local | staging | production")
    log_level: str = Field(default="INFO")

    # --- Google Cloud / Pub/Sub ---
    gcp_project_id: str = Field(..., description="GCP project id used for all Pub/Sub resources")

    pubsub_source_subscription_id: str = Field(
        ..., description="Subscription id the background listener pulls messages from"
    )
    pubsub_destination_topic_id: str = Field(
        ..., description="Topic id every forwarded message is published to"
    )

    pubsub_emulator_host: str | None = Field(
        default=None,
        description="Set to host:port to talk to a local Pub/Sub emulator instead of GCP",
    )

    # --- Pull subscriber tuning ---
    enable_pull_subscriber: bool = Field(
        default=True, description="Whether the background pull subscriber should start"
    )
    subscriber_max_messages: int = Field(default=50, ge=1)
    subscriber_ack_deadline_seconds: int = Field(default=60, ge=10)
    publish_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- Job dispatch (control plane -> agent-engine) ---
    pubsub_job_topic_id: str | None = Field(
        default=None,
        description=(
            "Topic agent job payloads are dispatched to. Falls back to "
            "PUBSUB_DESTINATION_TOPIC_ID when unset."
        ),
    )

    # --- Firestore (control plane store) ---
    firestore_project_id: str | None = Field(
        default=None,
        description="Firebase/Firestore project. Falls back to GCP_PROJECT_ID when unset.",
    )
    firestore_database: str = Field(
        default="(default)", description="Named Firestore database within the project"
    )
    firestore_collection_prefix: str = Field(
        default="",
        description=(
            "Prefix for every root collection, e.g. 'dev_' - lets several "
            "environments share one Firestore database"
        ),
    )
    firestore_emulator_host: str | None = Field(
        default=None,
        description="host:port of the Firebase emulator; bypasses credentials entirely",
    )

    # --- Context assembly defaults ---
    default_context_example_limit: int = Field(
        default=10, ge=0, le=200, description="Few-shot examples injected into a job payload"
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def resolved_firestore_project_id(self) -> str:
        """Project the Firestore client should target."""

        return self.firestore_project_id or self.gcp_project_id

    @property
    def job_topic_id(self) -> str:
        """Topic agent job payloads are published to."""

        return self.pubsub_job_topic_id or self.pubsub_destination_topic_id


@lru_cache
def get_settings() -> Settings:
    """Return a cached, process-wide ``Settings`` instance."""

    return Settings()  # type: ignore[call-arg]

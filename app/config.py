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

    pubsub_emulator_host: str | None = Field(
        default=None,
        description="Set to host:port to talk to a local Pub/Sub emulator instead of GCP",
    )

    publish_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- Job dispatch (control plane -> agent-engine) ---
    pubsub_job_topic_id: str = Field(
        ...,
        description=(
            "The one topic this service publishes to: agent-engine's run-jobs topic "
            "(e.g. karos-agent-runs-prep). Dispatch through POST /agents/{id}/jobs is "
            "the only thing that publishes, so there is exactly one destination."
        ),
    )

    # --- Service-to-service authentication ---
    auth_enabled: bool = Field(
        default=True,
        description=(
            "Verify the caller's identity on every non-health route. Leave on "
            "everywhere except local development."
        ),
    )
    auth_audience: str | None = Field(
        default=None,
        description=(
            "Expected 'aud' claim of an inbound OIDC token — this service's own Cloud "
            "Run URL. Required when auth_enabled and no dev token is configured."
        ),
    )
    auth_allowed_service_accounts: list[str] = Field(
        default_factory=list,
        description=(
            "Caller service-account emails allowed through. Empty means any identity "
            "Google will vouch for, which is only safe behind Cloud Run IAM."
        ),
    )
    auth_dev_token: str | None = Field(
        default=None,
        description=(
            "Static bearer token accepted INSTEAD of an OIDC token — for local dev and "
            "integration tests. Refused outright when environment=production."
        ),
    )

    # --- GCS (binary template assets) ---
    gcs_artifacts_bucket: str | None = Field(
        default=None,
        description=(
            "Bucket holding binary template assets (images, fonts). Firestore stores "
            "the gs:// URIs; the bytes live here."
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

        return self.pubsub_job_topic_id

    @property
    def dev_token_permitted(self) -> bool:
        """Whether the static dev token may be honoured.

        Never in production, regardless of what is configured: a shared secret in
        an environment variable is a development affordance, and the failure mode
        of leaving one set on a production deploy is silent, total auth bypass.
        """

        return self.auth_dev_token is not None and not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Return a cached, process-wide ``Settings`` instance."""

    return Settings()  # type: ignore[call-arg]

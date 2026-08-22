# Pub/Sub Bridge

A production-grade FastAPI service that bridges two Google Cloud Pub/Sub topics:

1. **Pull listener** — a background streaming-pull subscriber that consumes messages
   from a source subscription and republishes them to a destination topic.
2. **Push route** — `POST /pubsub/push`, compatible with a Google Cloud Pub/Sub
   **push subscription**, which decodes the delivered message and republishes it to
   the same destination topic.

Both paths share a single `MessageForwarder` service, so behavior (attribute
propagation, tracing, error handling) is identical regardless of how a message
arrives.

## Architecture

```
app/
  main.py                 FastAPI app factory, lifespan, exception handlers
  config.py               Settings (pydantic-settings, env-driven)
  logging_config.py       Logging setup
  dependencies.py         FastAPI dependency providers
  core/
    exceptions.py         Domain exceptions
  services/
    publisher.py          Async-friendly Pub/Sub publisher wrapper
    subscriber.py          Streaming-pull background subscriber
    forwarder.py           Shared forward-and-tag logic
  api/
    schemas/pubsub.py      Pub/Sub push envelope + response models
    routes/health.py       Liveness / readiness probes
    routes/pubsub.py       Push endpoint
tests/                    Pytest suite with fake Pub/Sub clients (no network/credentials needed)
```

## Configuration

Copy [.env.example](.env.example) to `.env` and adjust:

| Variable | Description |
|---|---|
| `GCP_PROJECT_ID` | GCP project containing the topics/subscriptions |
| `PUBSUB_SOURCE_SUBSCRIPTION_ID` | Subscription the background listener pulls from |
| `PUBSUB_DESTINATION_TOPIC_ID` | Topic every message is forwarded to |
| `PUBSUB_EMULATOR_HOST` | Optional, point at a local emulator instead of GCP |
| `ENABLE_PULL_SUBSCRIBER` | Set `false` to disable the background listener (push-only mode) |

Google credentials are resolved automatically via `GOOGLE_APPLICATION_CREDENTIALS`
or workload identity — no explicit key handling in application code.

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
```

## Running against the Pub/Sub emulator

```bash
gcloud beta emulators pubsub start --project=my-gcp-project
# in another shell
$env:PUBSUB_EMULATOR_HOST = "localhost:8085"
uvicorn app.main:app --reload --port 8080
```

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t pubsub-bridge .
docker run --rm -p 8080:8080 --env-file .env pubsub-bridge
```

## API

- `GET /health/live` — liveness probe.
- `GET /health/ready` — readiness probe (checks the background subscriber if enabled).
- `POST /pubsub/push` — Pub/Sub push subscription endpoint; forwards the message to the destination topic and returns `{ "forwarded_message_id": ..., "source_message_id": ... }`.

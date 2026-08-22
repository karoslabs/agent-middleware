"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Simple liveness probe: the process is up and serving requests."""

    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe: checks Firestore and the background subscriber."""

    settings = request.app.state.settings
    subscriber = getattr(request.app.state, "subscriber", None)
    database = getattr(request.app.state, "db", None)

    subscriber_running = bool(subscriber and subscriber.is_running)
    subscriber_ready = not settings.enable_pull_subscriber or subscriber_running
    firestore_ready = await database.ping() if database is not None else False

    is_ready = subscriber_ready and firestore_ready
    payload = {
        "status": "ok" if is_ready else "degraded",
        "firestore_reachable": firestore_ready,
        "pull_subscriber_running": subscriber_running,
    }
    return JSONResponse(
        content=payload,
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )

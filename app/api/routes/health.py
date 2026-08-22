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
    """Readiness probe: can this instance actually reach its store?

    Firestore is the only hard dependency of a control plane read. Pub/Sub is
    deliberately not probed: publishing happens on dispatch, and a broker blip
    should surface as a 502 on that one call rather than pulling the whole
    instance out of rotation.
    """

    database = getattr(request.app.state, "db", None)
    firestore_ready = await database.ping() if database is not None else False

    payload = {
        "status": "ok" if firestore_ready else "degraded",
        "firestore_reachable": firestore_ready,
    }
    return JSONResponse(
        content=payload,
        status_code=status.HTTP_200_OK if firestore_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )

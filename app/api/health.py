"""Health and readiness check endpoints."""

from typing import Dict
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health & Probes"])


class HealthResponse(BaseModel):
    """Schema for health status output."""
    status: str
    service: str
    environment: str


class ReadyResponse(BaseModel):
    """Schema for readiness probe output."""
    status: str
    checks: Dict[str, str]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def get_health() -> HealthResponse:
    """Return basic health status indicating the application process is running."""
    from app.config import get_settings

    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.APP_NAME,
        environment=settings.APP_ENV,
    )


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe")
def get_ready() -> ReadyResponse:
    """Return readiness status indicating the application is prepared to handle requests."""
    return ReadyResponse(
        status="ready",
        checks={
            "app": "ok",
            "configuration": "ok",
        },
    )

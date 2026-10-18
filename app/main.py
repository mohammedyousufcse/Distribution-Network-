"""Main entry point for the FastAPI distribution network application."""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api.connector import router as connector_router
from app.api.health import router as health_router
from app.config import get_settings
from app.logging import get_logger, setup_logging
from app.models.errors import ConnectorException

logger = get_logger("app.main")


def create_application() -> FastAPI:
    """Application factory for the FastAPI service."""
    settings = get_settings()

    # Initialize structured JSON logging
    setup_logging(settings.LOG_LEVEL)

    application = FastAPI(
        title=settings.APP_NAME,
        description="Distribution: Long-Tail Destination Network - Foundation Service",
        version="0.1.0",
        docs_url=settings.DOCS_URL,
        redoc_url=settings.REDOC_URL,
        openapi_url=settings.OPENAPI_URL,
    )

    # FastAPI 0.100+ uses OpenAPI 3.1.0 by default; explicitly verify/declare
    application.openapi_version = "3.1.0"

    # CORS middleware for cloud deployment (e.g. Render, Railway) and external clients
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register health and readiness routes at the root level (/health, /ready)
    application.include_router(health_router)

    # Register connector operations router (/connector/v1/...)
    application.include_router(connector_router)

    # Register structured error handler for connector exceptions
    @application.exception_handler(ConnectorException)
    def handle_connector_exception(request: Request, exc: ConnectorException) -> JSONResponse:
        logger.warning(
            f"Handled connector exception: {exc.error_code}",
            extra={
                "event": "connector_exception",
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "detail": exc.message,
                "path": request.url.path,
                "method": request.method,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    return application


app = create_application()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

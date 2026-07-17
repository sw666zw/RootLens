from fastapi import FastAPI

from inventory_service.api.health import router as health_router
from inventory_service.logging_config import configure_logging
from inventory_service.middleware.request_logging import RequestLoggingMiddleware


def create_app() -> FastAPI:
    """Create and configure the Inventory Service application."""
    configure_logging()
    application = FastAPI(
        title="RootLens Inventory Service",
        version="0.1.0",
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.include_router(health_router)
    return application


app = create_app()

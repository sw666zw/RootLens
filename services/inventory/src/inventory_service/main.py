from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from inventory_service.api.health import router as health_router
from inventory_service.api.items import router as items_router
from inventory_service.api.metrics import router as metrics_router
from inventory_service.database import DatabaseResources, database_resources
from inventory_service.logging_config import configure_logging
from inventory_service.metrics import create_metrics
from inventory_service.middleware.metrics import MetricsMiddleware
from inventory_service.middleware.request_logging import RequestLoggingMiddleware


def create_app(resources: DatabaseResources | None = None) -> FastAPI:
    """Create and configure the Inventory Service application."""
    configure_logging()
    application_resources = resources or database_resources
    application_metrics = create_metrics()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await application_resources.dispose()

    application = FastAPI(
        title="RootLens Inventory Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.database_resources = application_resources
    application.state.metrics = application_metrics
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(MetricsMiddleware, metrics=application_metrics)
    application.include_router(health_router)
    application.include_router(items_router)
    application.include_router(metrics_router)
    return application


app = create_app()

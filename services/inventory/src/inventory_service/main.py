from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from inventory_service.api.health import router as health_router
from inventory_service.api.items import router as items_router
from inventory_service.api.metrics import router as metrics_router
from inventory_service.database import DatabaseResources, create_database_resources
from inventory_service.logging_config import configure_logging
from inventory_service.metrics import create_metrics
from inventory_service.middleware.metrics import MetricsMiddleware
from inventory_service.middleware.request_logging import RequestLoggingMiddleware
from inventory_service.tracing import (
    TracingConfiguration,
    TracingResources,
    configure_tracing,
)


def create_app(
    resources: DatabaseResources | None = None,
    tracing: TracingConfiguration | None = None,
) -> FastAPI:
    """Create and configure the Inventory Service application."""
    configure_logging()
    application_resources = resources or create_database_resources()
    application_metrics = create_metrics()

    tracing_resources: TracingResources | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if tracing_resources is not None:
            tracing_resources.start()
        try:
            yield
        finally:
            try:
                await application_resources.dispose()
            finally:
                if tracing_resources is not None:
                    tracing_resources.shutdown()

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
    tracing_resources = configure_tracing(
        application,
        application_resources.engine,
        tracing,
    )
    application.state.tracing = tracing_resources
    return application


app = create_app()

"""FastAPI application factory for the Order Service."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from order_service.api.health import router as health_router
from order_service.api.metrics import router as metrics_router
from order_service.api.orders import router as orders_router
from order_service.clients import InventoryClient
from order_service.config import Settings
from order_service.database import DatabaseResources, create_database_resources
from order_service.logging_config import configure_logging
from order_service.metrics import create_metrics
from order_service.middleware.metrics import MetricsMiddleware
from order_service.middleware.request_logging import RequestLoggingMiddleware
from order_service.tracing import (
    TracingConfiguration,
    TracingResources,
    configure_tracing,
)

HttpClientFactory = Callable[[Settings], httpx.AsyncClient]


def _default_http_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.inventory_service_url,
        timeout=httpx.Timeout(15.0),
    )


def create_app(
    settings: Settings | None = None,
    resources: DatabaseResources | None = None,
    tracing: TracingConfiguration | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> FastAPI:
    """Create one independently testable Order Service application."""
    configure_logging()
    resolved_settings = settings or Settings.from_environment()
    application_resources = resources or create_database_resources()
    application_metrics = create_metrics()
    client_factory = http_client_factory or _default_http_client
    tracing_resources: TracingResources | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        client = client_factory(resolved_settings)
        application.state.http_client = client
        application.state.inventory_client = InventoryClient(client)
        if tracing_resources is not None:
            tracing_resources.start(client)
        try:
            yield
        finally:
            try:
                await application_resources.dispose()
            finally:
                try:
                    if tracing_resources is not None:
                        tracing_resources.shutdown()
                finally:
                    await client.aclose()

    application = FastAPI(
        title="RootLens Order Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database_resources = application_resources
    application.state.metrics = application_metrics
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(MetricsMiddleware, metrics=application_metrics)
    application.include_router(health_router)
    application.include_router(orders_router)
    application.include_router(metrics_router)
    tracing_resources = configure_tracing(
        application,
        application_resources.engine,
        tracing,
    )
    application.state.tracing = tracing_resources
    return application


app = create_app()

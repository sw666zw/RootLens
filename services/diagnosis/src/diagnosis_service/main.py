"""FastAPI application factory for the RootLens Diagnosis Service."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
from fastapi import FastAPI

from diagnosis_service.api.diagnoses import router as diagnoses_router
from diagnosis_service.api.explanations import router as explanations_router
from diagnosis_service.api.health import router as health_router
from diagnosis_service.api.incidents import router as incidents_router
from diagnosis_service.api.metrics import router as metrics_router
from diagnosis_service.config import Settings
from diagnosis_service.logging_config import configure_logging
from diagnosis_service.metrics import create_metrics
from diagnosis_service.middleware.metrics import MetricsMiddleware
from diagnosis_service.middleware.request_logging import RequestLoggingMiddleware
from diagnosis_service.repositories.report_files import ReportRepositories
from diagnosis_service.services.diagnosis import DiagnosisService, TelemetryClients
from diagnosis_service.services.explanations import ExplanationService
from diagnosis_service.tracing import (
    TracingConfiguration,
    TracingResources,
    configure_tracing,
)

HttpClients = tuple[httpx.AsyncClient, httpx.AsyncClient, httpx.AsyncClient]
HttpClientFactory = Callable[[Settings], HttpClients]


def _http_clients(settings: Settings) -> HttpClients:
    timeout = httpx.Timeout(settings.diagnosis.timeout_seconds)
    return (
        httpx.AsyncClient(base_url=settings.diagnosis.prometheus_url, timeout=timeout),
        httpx.AsyncClient(base_url=settings.diagnosis.loki_url, timeout=timeout),
        httpx.AsyncClient(base_url=settings.diagnosis.jaeger_url, timeout=timeout),
    )


def create_app(
    settings: Settings | None = None,
    *,
    diagnosis_service: DiagnosisService | None = None,
    explanation_service: ExplanationService | None = None,
    http_client_factory: HttpClientFactory | None = None,
    tracing: TracingConfiguration | None = None,
) -> FastAPI:
    """Build one isolated, replaceable Diagnosis Service application."""
    configure_logging()
    resolved = settings or Settings.from_environment()
    repositories = ReportRepositories.create(
        resolved.incident_output_dir,
        resolved.diagnosis.output_dir,
        resolved.explanation.output_dir,
    )
    metrics = create_metrics()
    client_factory = http_client_factory or _http_clients
    tracing_resources: TracingResources | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        clients: HttpClients | None = None
        try:
            if diagnosis_service is None:
                clients = client_factory(resolved)
                application.state.diagnosis_service = DiagnosisService(
                    replace(
                        resolved.diagnosis,
                        output_dir=repositories.diagnoses.root,
                    ),
                    TelemetryClients(*clients),
                )
                if tracing_resources is not None:
                    tracing_resources.start(clients)
            yield
        finally:
            if tracing_resources is not None:
                tracing_resources.shutdown()
            if clients is not None:
                for client in clients:
                    await client.aclose()

    application = FastAPI(
        title="RootLens Diagnosis Service", version="0.1.0", lifespan=lifespan
    )
    application.state.settings = resolved
    application.state.repositories = repositories
    application.state.metrics = metrics
    if diagnosis_service is not None:
        application.state.diagnosis_service = diagnosis_service
    application.state.explanation_service = explanation_service or ExplanationService(
        replace(
            resolved.explanation,
            output_dir=repositories.explanations.root,
        )
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(MetricsMiddleware, metrics=metrics)
    application.include_router(health_router)
    application.include_router(incidents_router)
    application.include_router(diagnoses_router)
    application.include_router(explanations_router)
    application.include_router(metrics_router)
    tracing_resources = configure_tracing(application, tracing)
    application.state.tracing = tracing_resources
    return application


app = create_app()

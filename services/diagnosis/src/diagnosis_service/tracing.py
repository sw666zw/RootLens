"""Application-scoped OpenTelemetry tracing."""

import os
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanProcessor,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
)

SpanProcessorFactory = Callable[[SpanExporter], SpanProcessor]


def _redact_httpx_url(span: object, request: object) -> None:
    """Keep a telemetry route without query data or concrete trace IDs."""
    url = getattr(request, "url", None)
    path = getattr(url, "path", "")
    if path.startswith("/api/v3/traces/"):
        path = "/api/v3/traces/{trace_id}"
    elif path not in {
        "/api/v1/query",
        "/api/v1/query_range",
        "/loki/api/v1/query_range",
    }:
        path = "/telemetry"
    if hasattr(span, "set_attribute"):
        span.set_attribute("url.full", path)
        span.set_attribute("http.url", path)


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes"}


def _sampler(name: str) -> Sampler:
    try:
        return {
            "always_on": ALWAYS_ON,
            "always_off": ALWAYS_OFF,
            "parentbased_always_on": ParentBased(ALWAYS_ON),
            "parentbased_always_off": ParentBased(ALWAYS_OFF),
        }[name.lower()]
    except KeyError as error:
        raise ValueError("Unsupported OTEL_TRACES_SAMPLER.") from error


@dataclass(frozen=True)
class TracingSettings:
    enabled: bool
    service_name: str
    exporter_endpoint: str
    exporter_insecure: bool
    sampler_name: str

    @classmethod
    def from_environment(cls) -> "TracingSettings":
        name = os.getenv("DIAGNOSIS_OTEL_SERVICE_NAME", "rootlens-diagnosis").strip()
        if not name:
            raise ValueError("DIAGNOSIS_OTEL_SERVICE_NAME must not be blank.")
        return cls(
            enabled=_boolean("OTEL_TRACES_ENABLED", False),
            service_name=name,
            exporter_endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
            ),
            exporter_insecure=_boolean("OTEL_EXPORTER_OTLP_INSECURE", True),
            sampler_name=os.getenv("OTEL_TRACES_SAMPLER", "always_on"),
        )


@dataclass(frozen=True)
class TracingConfiguration:
    settings: TracingSettings
    span_exporter: SpanExporter | None = None
    span_processor_factory: SpanProcessorFactory = BatchSpanProcessor


@dataclass
class TracingResources:
    provider: TracerProvider
    app: FastAPI
    instrumentor: HTTPXClientInstrumentor
    clients: tuple[httpx.AsyncClient, ...] = ()
    closed: bool = False

    def start(self, clients: tuple[httpx.AsyncClient, ...]) -> None:
        if self.closed or self.clients:
            return
        for client in clients:
            self.instrumentor.instrument_client(
                client,
                tracer_provider=self.provider,
                request_hook=_redact_httpx_url,
            )
        self.clients = clients

    def shutdown(self) -> None:
        if self.closed:
            return
        FastAPIInstrumentor.uninstrument_app(self.app)
        for client in self.clients:
            self.instrumentor.uninstrument_client(client)
        self.provider.force_flush()
        self.provider.shutdown()
        self.closed = True


def configure_tracing(
    app: FastAPI, configuration: TracingConfiguration | None = None
) -> TracingResources | None:
    resolved = configuration or TracingConfiguration(TracingSettings.from_environment())
    if not resolved.settings.enabled:
        return None
    settings = resolved.settings
    provider = TracerProvider(
        sampler=_sampler(settings.sampler_name),
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.namespace": "rootlens",
                "deployment.environment.name": "local",
            }
        ),
    )
    exporter = resolved.span_exporter or OTLPSpanExporter(
        endpoint=settings.exporter_endpoint, insecure=settings.exporter_insecure
    )
    provider.add_span_processor(resolved.span_processor_factory(exporter))
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls=r"^.*/metrics$"
    )
    return TracingResources(provider, app, HTTPXClientInstrumentor())


def current_trace_ids() -> tuple[str, str] | None:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def set_span_attributes(attributes: dict[str, object]) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attributes(attributes)

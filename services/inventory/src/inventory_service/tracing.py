"""Application-scoped OpenTelemetry tracing for the Inventory Service."""

import os
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
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
from sqlalchemy.ext.asyncio import AsyncEngine

DEFAULT_SERVICE_NAME = "rootlens-inventory"
SERVICE_NAMESPACE = "rootlens"
DEPLOYMENT_ENVIRONMENT = "local"
METRICS_EXCLUDED_URLS = r"^.*/metrics$"

SpanProcessorFactory = Callable[[SpanExporter], SpanProcessor]


def _environment_boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _sampler(name: str) -> Sampler:
    samplers = {
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
        "parentbased_always_on": ParentBased(ALWAYS_ON),
        "parentbased_always_off": ParentBased(ALWAYS_OFF),
    }
    try:
        return samplers[name.lower()]
    except KeyError as error:
        supported = ", ".join(sorted(samplers))
        raise ValueError(
            f"Unsupported OTEL_TRACES_SAMPLER {name!r}; expected one of {supported}."
        ) from error


@dataclass(frozen=True)
class TracingSettings:
    """Environment-driven tracing settings."""

    enabled: bool
    service_name: str
    exporter_endpoint: str
    exporter_insecure: bool
    sampler_name: str

    @classmethod
    def from_environment(cls) -> "TracingSettings":
        """Load tracing settings without requiring a dotenv dependency."""
        return cls(
            enabled=_environment_boolean("OTEL_TRACES_ENABLED", False),
            service_name=os.getenv("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME),
            exporter_endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "http://localhost:4317",
            ),
            exporter_insecure=_environment_boolean(
                "OTEL_EXPORTER_OTLP_INSECURE",
                True,
            ),
            sampler_name=os.getenv("OTEL_TRACES_SAMPLER", "always_on"),
        )


@dataclass(frozen=True)
class TracingConfiguration:
    """Optional dependencies used to configure and test tracing."""

    settings: TracingSettings
    span_exporter: SpanExporter | None = None
    span_processor_factory: SpanProcessorFactory = BatchSpanProcessor


@dataclass
class TracingResources:
    """Tracing resources owned by one Inventory Service application."""

    provider: TracerProvider
    sqlalchemy_instrumentor: SQLAlchemyInstrumentor
    engine: AsyncEngine
    app: FastAPI
    sqlalchemy_instrumented: bool = False
    closed: bool = False

    def start(self) -> None:
        """Instrument SQLAlchemy when the application lifespan starts."""
        if self.closed or self.sqlalchemy_instrumented:
            return
        self.sqlalchemy_instrumentor.instrument(
            engine=self.engine.sync_engine,
            tracer_provider=self.provider,
        )
        self.sqlalchemy_instrumented = True

    def shutdown(self) -> None:
        """Remove instrumentation and flush all pending spans once."""
        if self.closed:
            return
        FastAPIInstrumentor.uninstrument_app(self.app)
        if self.sqlalchemy_instrumented:
            self.sqlalchemy_instrumentor.uninstrument()
        self.provider.force_flush()
        self.provider.shutdown()
        self.closed = True


def configure_tracing(
    app: FastAPI,
    engine: AsyncEngine,
    configuration: TracingConfiguration | None = None,
) -> TracingResources | None:
    """Instrument one application and async SQLAlchemy engine when enabled."""
    resolved = configuration or TracingConfiguration(
        settings=TracingSettings.from_environment()
    )
    if not resolved.settings.enabled:
        return None

    settings = resolved.settings
    provider = TracerProvider(
        sampler=_sampler(settings.sampler_name),
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.namespace": SERVICE_NAMESPACE,
                "deployment.environment.name": DEPLOYMENT_ENVIRONMENT,
            }
        ),
    )
    exporter = resolved.span_exporter or OTLPSpanExporter(
        endpoint=settings.exporter_endpoint,
        insecure=settings.exporter_insecure,
    )
    provider.add_span_processor(resolved.span_processor_factory(exporter))

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=METRICS_EXCLUDED_URLS,
    )
    return TracingResources(
        provider=provider,
        sqlalchemy_instrumentor=SQLAlchemyInstrumentor(),
        engine=engine,
        app=app,
    )


def current_trace_ids() -> tuple[str, str] | None:
    """Return valid lowercase trace and span IDs for the active span."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def set_current_span_attributes(attributes: dict[str, object]) -> None:
    """Add safe attributes when the current span is recording."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attributes(attributes)

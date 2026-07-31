"""Application-scoped Prometheus metrics for the Order Service."""

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

HTTP_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


@dataclass(frozen=True)
class OrderMetrics:
    """Registry and collectors owned by one FastAPI application."""

    registry: CollectorRegistry
    http_requests: Counter
    http_request_duration: Histogram
    http_errors: Counter
    creations: Counter
    status_transitions: Counter
    database_ready: Gauge


def create_metrics() -> OrderMetrics:
    """Create an isolated registry and Order Service collectors."""
    registry = CollectorRegistry()
    return OrderMetrics(
        registry=registry,
        http_requests=Counter(
            "rootlens_order_http_requests_total",
            "Completed Order Service HTTP requests.",
            ("method", "route", "status_code"),
            registry=registry,
        ),
        http_request_duration=Histogram(
            "rootlens_order_http_request_duration_seconds",
            "Duration of completed Order Service HTTP requests in seconds.",
            ("method", "route"),
            buckets=HTTP_LATENCY_BUCKETS,
            registry=registry,
        ),
        http_errors=Counter(
            "rootlens_order_http_errors_total",
            "Completed Order Service HTTP requests with an error status.",
            ("method", "route", "status_code"),
            registry=registry,
        ),
        creations=Counter(
            "rootlens_order_creations_total",
            "Order creation attempts by outcome and reason.",
            ("outcome", "reason"),
            registry=registry,
        ),
        status_transitions=Counter(
            "rootlens_order_status_transitions_total",
            "Successfully persisted Order status transitions.",
            ("from_status", "to_status"),
            registry=registry,
        ),
        database_ready=Gauge(
            "rootlens_order_database_ready",
            "Whether the Order database passed its latest readiness check.",
            registry=registry,
        ),
    )

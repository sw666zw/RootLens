"""Application-scoped Prometheus metrics for the Inventory Service."""

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Histogram

HTTP_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


@dataclass(frozen=True)
class InventoryMetrics:
    """Registry and collectors owned by one FastAPI application."""

    registry: CollectorRegistry
    http_requests: Counter
    http_request_duration: Histogram
    http_errors: Counter
    reservations: Counter


def create_metrics() -> InventoryMetrics:
    """Create an isolated registry and the Inventory Service collectors."""
    registry = CollectorRegistry()
    return InventoryMetrics(
        registry=registry,
        http_requests=Counter(
            "rootlens_inventory_http_requests_total",
            "Completed Inventory Service HTTP requests.",
            ("method", "route", "status_code"),
            registry=registry,
        ),
        http_request_duration=Histogram(
            "rootlens_inventory_http_request_duration_seconds",
            "Duration of completed Inventory Service HTTP requests in seconds.",
            ("method", "route"),
            buckets=HTTP_LATENCY_BUCKETS,
            registry=registry,
        ),
        http_errors=Counter(
            "rootlens_inventory_http_errors_total",
            "Completed Inventory Service HTTP requests with an error status.",
            ("method", "route", "status_code"),
            registry=registry,
        ),
        reservations=Counter(
            "rootlens_inventory_reservations_total",
            "Inventory reservation attempts by outcome and reason.",
            ("outcome", "reason"),
            registry=registry,
        ),
    )

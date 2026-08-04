"""Typed normalized telemetry inputs and source results."""

from dataclasses import dataclass, field
from datetime import datetime

from rootlens_diagnosis.models import Evidence, SourceStatus


@dataclass(frozen=True)
class SourceResult[T]:
    status: SourceStatus
    data: T
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricSample:
    labels: dict[str, str]
    timestamp: float
    value: float


@dataclass(frozen=True)
class PrometheusData:
    queries: dict[str, tuple[MetricSample, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class LogEntry:
    timestamp_ns: int
    service: str
    category: str
    level: str | None
    request_id: str | None
    trace_id: str | None
    status_code: int | None
    duration_ms: float | None
    reason: str | None


@dataclass(frozen=True)
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    name: str
    kind: str
    start_time: datetime
    duration_ms: float
    error: bool
    attributes: dict[str, str | int | float | bool]


@dataclass(frozen=True)
class TraceData:
    trace_id: str
    spans: tuple[TraceSpan, ...]


@dataclass(frozen=True)
class MetricsFeatures:
    order_requests: float | None = None
    order_5xx: float | None = None
    order_503: float | None = None
    order_p95_ms: float | None = None
    inventory_requests: float | None = None
    inventory_5xx: float | None = None
    inventory_503: float | None = None
    inventory_p95_ms: float | None = None
    order_confirmed: float | None = None
    order_rejected: float | None = None
    order_failed: float | None = None
    reservation_success: float | None = None
    reservation_failed: float | None = None
    order_up_ratio: float | None = None
    inventory_up_ratio: float | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class LogFeatures:
    entries: tuple[LogEntry, ...] = ()
    order_status_counts: dict[int, int] = field(default_factory=dict)
    categories: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, int] = field(default_factory=dict)
    shared_request_ids: int = 0
    shared_trace_ids: int = 0
    warning_count: int = 0
    error_count: int = 0
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class TraceFeatures:
    trace_ids: tuple[str, ...] = ()
    trace_count: int = 0
    cross_service_count: int = 0
    successful_reservations: int = 0
    failed_inventory_traces: int = 0
    failed_without_database: int = 0
    order_server_p95_ms: float | None = None
    inventory_server_p95_ms: float | None = None
    order_inventory_client_p95_ms: float | None = None
    database_span_count: int = 0
    database_duration_ms: float = 0.0
    error_span_count: int = 0
    slowest_service: str | None = None
    slowest_span_category: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class NormalizedTelemetry:
    metrics: SourceResult[MetricsFeatures]
    logs: SourceResult[LogFeatures]
    traces: SourceResult[TraceFeatures]

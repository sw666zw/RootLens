"""Derive safe latency, failure-location, and database trace features."""

from collections import defaultdict
from statistics import quantiles

from rootlens_diagnosis.models import Evidence, EvidenceSeverity, EvidenceSource
from rootlens_diagnosis.telemetry.models import TraceData, TraceFeatures, TraceSpan


def extract_traces(traces: tuple[TraceData, ...]) -> TraceFeatures:
    order_server: list[float] = []
    inventory_server: list[float] = []
    outgoing: list[float] = []
    database_spans: list[TraceSpan] = []
    cross_service = 0
    successes = 0
    failed_inventory = 0
    failed_without_database = 0
    error_spans = 0
    service_durations: dict[str, float] = defaultdict(float)
    category_durations: dict[str, float] = defaultdict(float)
    for trace in traces:
        services = {_service(span.service) for span in trace.spans}
        if {"order", "inventory"}.issubset(services):
            cross_service += 1
        trace_database = [span for span in trace.spans if _is_database(span)]
        inventory_database = [
            span for span in trace_database if _service(span.service) == "inventory"
        ]
        database_spans.extend(trace_database)
        inventory_failed = False
        for span in trace.spans:
            service = _service(span.service)
            category = _span_category(span)
            service_durations[service] += span.duration_ms
            category_durations[category] += span.duration_ms
            error_spans += span.error
            if service == "order" and _is_server(span):
                order_server.append(span.duration_ms)
            if service == "inventory" and _is_server(span):
                inventory_server.append(span.duration_ms)
                outcome = span.attributes.get("rootlens.inventory.outcome")
                if outcome == "success" and not span.error:
                    successes += 1
                if span.error or outcome in {"service_unavailable", "database_error"}:
                    inventory_failed = True
            if service == "order" and _is_client(span):
                outgoing.append(span.duration_ms)
        if inventory_failed:
            failed_inventory += 1
            if not inventory_database:
                failed_without_database += 1
    slowest_service = max(service_durations, key=service_durations.get, default=None)
    slowest_category = max(category_durations, key=category_durations.get, default=None)
    features = TraceFeatures(
        trace_ids=tuple(trace.trace_id for trace in traces),
        trace_count=len(traces),
        cross_service_count=cross_service,
        successful_reservations=successes,
        failed_inventory_traces=failed_inventory,
        failed_without_database=failed_without_database,
        order_server_p95_ms=_p95(order_server),
        inventory_server_p95_ms=_p95(inventory_server),
        order_inventory_client_p95_ms=_p95(outgoing),
        database_span_count=len(database_spans),
        database_duration_ms=sum(span.duration_ms for span in database_spans),
        error_span_count=error_spans,
        slowest_service=slowest_service,
        slowest_span_category=slowest_category,
    )
    return TraceFeatures(
        **{**features.__dict__, "evidence": tuple(_evidence(features))}
    )


def _evidence(features: TraceFeatures) -> list[Evidence]:
    if not features.trace_ids:
        return []
    reference = features.trace_ids[0]
    values = [
        ("trace_count", float(features.trace_count), "traces", None),
        ("cross_service_traces", float(features.cross_service_count), "traces", None),
        ("order_server_p95_latency", features.order_server_p95_ms, "ms", "order"),
        (
            "inventory_server_p95_latency",
            features.inventory_server_p95_ms,
            "ms",
            "inventory",
        ),
        (
            "order_inventory_client_p95_latency",
            features.order_inventory_client_p95_ms,
            "ms",
            "order",
        ),
        ("database_span_count", float(features.database_span_count), "spans", None),
        ("error_span_count", float(features.error_span_count), "spans", None),
        (
            "failed_before_database",
            float(features.failed_without_database),
            "traces",
            "inventory",
        ),
    ]
    return [
        Evidence(
            source=EvidenceSource.TRACES,
            signal=signal,
            observation=f"{signal.replace('_', ' ')} was {value:.3f}",
            value=value,
            unit=unit,
            service=service,
            severity=EvidenceSeverity.INFORMATIONAL,
            reference=reference,
        )
        for signal, value, unit, service in values
        if value is not None
    ]


def _service(value: str) -> str:
    lowered = value.lower()
    if "inventory" in lowered:
        return "inventory"
    if "order" in lowered:
        return "order"
    return lowered


def _is_server(span: TraceSpan) -> bool:
    return span.kind in {"2", "SPAN_KIND_SERVER", "SERVER"}


def _is_client(span: TraceSpan) -> bool:
    return span.kind in {"3", "SPAN_KIND_CLIENT", "CLIENT"}


def _is_database(span: TraceSpan) -> bool:
    return "db.system" in span.attributes or "db.system.name" in span.attributes


def _span_category(span: TraceSpan) -> str:
    if _is_database(span):
        return "database"
    if _is_client(span):
        return "http_client"
    if _is_server(span):
        return "http_server"
    return "internal"


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=100, method="inclusive")[94]

"""Normalize fixed Prometheus query results into diagnosis features."""

import math

from rootlens_diagnosis.models import (
    Evidence,
    EvidenceSeverity,
    EvidenceSource,
)
from rootlens_diagnosis.telemetry.models import MetricsFeatures, PrometheusData


def _sum(
    data: PrometheusData,
    query: str,
    *,
    labels: dict[str, str] | None = None,
    status_prefix: str | None = None,
) -> float | None:
    samples = data.queries.get(query)
    if samples is None:
        return None
    selected = []
    for sample in samples:
        if labels and any(
            sample.labels.get(key) != value for key, value in labels.items()
        ):
            continue
        if status_prefix and not sample.labels.get("status_code", "").startswith(
            status_prefix
        ):
            continue
        if math.isfinite(sample.value):
            selected.append(sample.value)
    return sum(selected) if selected else None


def _last_value(data: PrometheusData, query: str) -> float | None:
    samples = data.queries.get(query)
    if not samples:
        return None
    return next(
        (sample.value for sample in reversed(samples) if math.isfinite(sample.value)),
        None,
    )


def _up_ratio(data: PrometheusData, query: str) -> float | None:
    samples = data.queries.get(query)
    if not samples:
        return None
    finite = [sample.value for sample in samples if math.isfinite(sample.value)]
    if not finite:
        return None
    return sum(value > 0 for value in finite) / len(finite)


def extract_metrics(data: PrometheusData) -> MetricsFeatures:
    order_route = {"route": "/orders"}
    inventory_route = {"route": "/items/{sku}/reserve"}
    order_requests = _sum(data, "order_requests", labels=order_route)
    order_5xx = _sum(data, "order_requests", labels=order_route, status_prefix="5")
    order_503 = _sum(
        data,
        "order_requests",
        labels={**order_route, "status_code": "503"},
    )
    inventory_requests = _sum(data, "inventory_requests", labels=inventory_route)
    inventory_5xx = _sum(
        data, "inventory_requests", labels=inventory_route, status_prefix="5"
    )
    inventory_503 = _sum(
        data,
        "inventory_requests",
        labels={**inventory_route, "status_code": "503"},
    )
    order_p95 = _last_value(data, "order_p95")
    inventory_p95 = _last_value(data, "inventory_p95")
    order_confirmed = _sum(data, "order_creations", labels={"outcome": "confirmed"})
    order_rejected = _sum(data, "order_creations", labels={"outcome": "rejected"})
    order_failed = _sum(data, "order_creations", labels={"outcome": "error"})
    reservation_success = _sum(
        data, "inventory_reservations", labels={"outcome": "success"}
    )
    reservation_failed = _sum(
        data, "inventory_reservations", labels={"outcome": "error"}
    )
    evidence: list[Evidence] = []
    observations = [
        ("order_request_count", order_requests, "requests", "order", "order_requests"),
        ("order_5xx_count", order_5xx, "requests", "order", "order_requests"),
        ("order_503_count", order_503, "requests", "order", "order_requests"),
        ("order_p95_latency", _milliseconds(order_p95), "ms", "order", "order_p95"),
        (
            "inventory_request_count",
            inventory_requests,
            "requests",
            "inventory",
            "inventory_requests",
        ),
        (
            "inventory_5xx_count",
            inventory_5xx,
            "requests",
            "inventory",
            "inventory_requests",
        ),
        (
            "inventory_503_count",
            inventory_503,
            "requests",
            "inventory",
            "inventory_requests",
        ),
        (
            "inventory_p95_latency",
            _milliseconds(inventory_p95),
            "ms",
            "inventory",
            "inventory_p95",
        ),
        ("confirmed_orders", order_confirmed, "orders", "order", "order_creations"),
        ("failed_orders", order_failed, "orders", "order", "order_creations"),
        (
            "successful_reservations",
            reservation_success,
            "reservations",
            "inventory",
            "inventory_reservations",
        ),
        (
            "failed_reservations",
            reservation_failed,
            "reservations",
            "inventory",
            "inventory_reservations",
        ),
        ("order_up_ratio", _up_ratio(data, "order_up"), "ratio", "order", "order_up"),
        (
            "inventory_up_ratio",
            _up_ratio(data, "inventory_up"),
            "ratio",
            "inventory",
            "inventory_up",
        ),
    ]
    for signal, value, unit, service, reference in observations:
        if value is not None:
            evidence.append(
                Evidence(
                    source=EvidenceSource.METRICS,
                    signal=signal,
                    observation=f"{signal.replace('_', ' ')} was {value:.3f}",
                    value=value,
                    unit=unit,
                    service=service,
                    severity=EvidenceSeverity.INFORMATIONAL,
                    reference=reference,
                )
            )
    return MetricsFeatures(
        order_requests=order_requests,
        order_5xx=order_5xx,
        order_503=order_503,
        order_p95_ms=_milliseconds(order_p95),
        inventory_requests=inventory_requests,
        inventory_5xx=inventory_5xx,
        inventory_503=inventory_503,
        inventory_p95_ms=_milliseconds(inventory_p95),
        order_confirmed=order_confirmed,
        order_rejected=order_rejected,
        order_failed=order_failed,
        reservation_success=reservation_success,
        reservation_failed=reservation_failed,
        order_up_ratio=_up_ratio(data, "order_up"),
        inventory_up_ratio=_up_ratio(data, "inventory_up"),
        evidence=tuple(evidence),
    )


def _milliseconds(seconds: float | None) -> float | None:
    return None if seconds is None else seconds * 1000

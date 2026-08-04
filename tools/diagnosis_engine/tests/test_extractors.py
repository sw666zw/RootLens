from rootlens_diagnosis.extractors.metrics import extract_metrics
from rootlens_diagnosis.extractors.traces import extract_traces
from rootlens_diagnosis.telemetry.models import (
    MetricSample,
    PrometheusData,
    TraceData,
    TraceSpan,
)


def test_metrics_normalize_error_counts_and_p95() -> None:
    sample = lambda labels, value: MetricSample(labels, 1.0, value)  # noqa: E731
    data = PrometheusData(
        {
            "order_requests": (
                sample({"route": "/orders", "status_code": "201"}, 18),
                sample({"route": "/orders", "status_code": "503"}, 2),
            ),
            "order_p95": (sample({}, 1.25),),
        }
    )
    features = extract_metrics(data)
    assert features.order_requests == 20
    assert features.order_5xx == 2
    assert features.order_503 == 2
    assert features.order_p95_ms == 1250
    assert features.inventory_requests is None


def test_non_finite_prometheus_values_are_missing_not_zero_or_healthy() -> None:
    data = PrometheusData(
        {
            "order_requests": (
                MetricSample(
                    {"route": "/orders", "status_code": "201"}, 1, float("nan")
                ),
            ),
            "order_p95": (MetricSample({}, 1, float("nan")),),
            "order_up": (MetricSample({}, 1, float("inf")),),
        }
    )

    features = extract_metrics(data)

    assert features.order_requests is None
    assert features.order_5xx is None
    assert features.order_p95_ms is None
    assert features.order_up_ratio is None


def test_trace_extractor_recognizes_cross_service_and_database(
    context: object,
) -> None:
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    start = context.started_at  # type: ignore[attr-defined]
    spans = (
        TraceSpan(
            trace_id,
            "1",
            None,
            "rootlens-order",
            "POST /orders",
            "SPAN_KIND_SERVER",
            start,
            1600,
            False,
            {},
        ),
        TraceSpan(
            trace_id,
            "2",
            "1",
            "rootlens-inventory",
            "POST /items/{sku}/reserve",
            "SPAN_KIND_SERVER",
            start,
            1500,
            False,
            {"rootlens.inventory.outcome": "success"},
        ),
        TraceSpan(
            trace_id,
            "3",
            "2",
            "rootlens-inventory",
            "database operation",
            "SPAN_KIND_INTERNAL",
            start,
            10,
            False,
            {"db.system": "postgresql"},
        ),
    )
    features = extract_traces((TraceData(trace_id, spans),))
    assert features.cross_service_count == 1
    assert features.inventory_server_p95_ms == 1500
    assert features.database_span_count == 1


def test_failed_inventory_before_database_ignores_order_database(
    context: object,
) -> None:
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    start = context.started_at  # type: ignore[attr-defined]
    spans = (
        TraceSpan(
            trace_id,
            "1",
            None,
            "rootlens-order",
            "order database operation",
            "SPAN_KIND_INTERNAL",
            start,
            5,
            False,
            {"db.system": "postgresql"},
        ),
        TraceSpan(
            trace_id,
            "2",
            "1",
            "rootlens-inventory",
            "POST /items/{sku}/reserve",
            "SPAN_KIND_SERVER",
            start,
            10,
            True,
            {"rootlens.inventory.outcome": "service_unavailable"},
        ),
    )
    features = extract_traces((TraceData(trace_id, spans),))
    assert features.failed_inventory_traces == 1
    assert features.failed_without_database == 1

from rootlens_diagnosis.engine import DiagnosisEngine
from rootlens_diagnosis.models import RootCause, SourceStatus
from rootlens_diagnosis.telemetry.models import (
    LogFeatures,
    MetricsFeatures,
    NormalizedTelemetry,
    SourceResult,
    TraceFeatures,
)


def test_supported_incidents_are_diagnosed(
    context: object,
    window: object,
    healthy_telemetry: NormalizedTelemetry,
    slow_telemetry: NormalizedTelemetry,
    unavailable_telemetry: NormalizedTelemetry,
) -> None:
    engine = DiagnosisEngine()
    expected = [
        RootCause.NONE,
        RootCause.INVENTORY_RESERVATION_LATENCY,
        RootCause.INVENTORY_SERVICE_UNAVAILABLE,
    ]
    reports = [
        engine.analyze(context, window, telemetry)  # type: ignore[arg-type]
        for telemetry in (
            healthy_telemetry,
            slow_telemetry,
            unavailable_telemetry,
        )
    ]
    assert [report.suspected_root_cause for report in reports] == expected
    assert all(report.candidate_scores for report in reports)
    assert all(
        score.supporting_evidence or score.contradicting_evidence
        for report in reports
        for cause, score in report.candidate_scores.items()
        if cause is not RootCause.UNKNOWN
    )


def test_normal_latency_closes_healthy_multi_source_score_gap(
    context: object,
    window: object,
) -> None:
    """Match a report with NaN metric p95 but valid healthy trace latency."""
    telemetry = NormalizedTelemetry(
        SourceResult(
            SourceStatus.AVAILABLE,
            MetricsFeatures(order_p95_ms=float("nan"), inventory_p95_ms=float("nan")),
        ),
        SourceResult(
            SourceStatus.AVAILABLE,
            LogFeatures(categories={"order_creation_succeeded": 20}),
        ),
        SourceResult(
            SourceStatus.AVAILABLE,
            TraceFeatures(
                trace_count=20,
                successful_reservations=20,
                error_span_count=0,
                order_server_p95_ms=218,
                inventory_server_p95_ms=76,
                order_inventory_client_p95_ms=55,
            ),
        ),
    )

    report = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, telemetry
    )

    assert report.suspected_root_cause is RootCause.NONE
    none_score = report.candidate_scores[RootCause.NONE]
    assert none_score.score >= 0.45
    assert "traces:normal_order_latency" in none_score.supporting_evidence
    assert "traces:normal_inventory_latency" in none_score.supporting_evidence
    assert not any(
        reference.startswith("metrics:normal_")
        for reference in none_score.supporting_evidence
    )
    latency_score = report.candidate_scores[RootCause.INVENTORY_RESERVATION_LATENCY]
    assert "traces:normal_inventory_server_latency" in (
        latency_score.contradicting_evidence
    )
    assert "traces:normal_order_inventory_client_latency" in (
        latency_score.contradicting_evidence
    )


def test_weak_evidence_returns_unknown(context: object, window: object) -> None:
    telemetry = NormalizedTelemetry(
        SourceResult(SourceStatus.PARTIAL, MetricsFeatures(order_requests=20)),
        SourceResult(SourceStatus.PARTIAL, LogFeatures()),
        SourceResult(SourceStatus.PARTIAL, TraceFeatures()),
    )
    report = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, telemetry
    )
    assert report.suspected_root_cause is RootCause.UNKNOWN
    assert report.confidence == 0


def test_missing_metrics_are_not_counted_as_healthy(
    context: object,
    window: object,
) -> None:
    telemetry = NormalizedTelemetry(
        SourceResult(SourceStatus.AVAILABLE, MetricsFeatures()),
        SourceResult(
            SourceStatus.AVAILABLE,
            LogFeatures(categories={"order_creation_succeeded": 20}),
        ),
        SourceResult(
            SourceStatus.AVAILABLE,
            TraceFeatures(
                trace_count=20,
                successful_reservations=20,
                error_span_count=0,
            ),
        ),
    )

    report = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, telemetry
    )

    assert report.suspected_root_cause is RootCause.UNKNOWN
    supporting = report.candidate_scores[RootCause.NONE].supporting_evidence
    assert not any(reference.startswith("metrics:") for reference in supporting)


def test_one_source_cannot_be_high_confidence(
    context: object,
    window: object,
) -> None:
    telemetry = NormalizedTelemetry(
        SourceResult(
            SourceStatus.AVAILABLE,
            MetricsFeatures(
                order_requests=20,
                order_5xx=20,
                order_503=20,
                inventory_requests=20,
                inventory_503=20,
                reservation_failed=20,
            ),
        ),
        SourceResult(SourceStatus.UNAVAILABLE, LogFeatures()),
        SourceResult(SourceStatus.UNAVAILABLE, TraceFeatures()),
    )
    report = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, telemetry
    )
    assert report.suspected_root_cause is RootCause.INVENTORY_SERVICE_UNAVAILABLE
    assert report.confidence < 0.8


def test_missing_telemetry_reduces_confidence(
    context: object,
    window: object,
    unavailable_telemetry: NormalizedTelemetry,
) -> None:
    complete = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, unavailable_telemetry
    )
    partial = NormalizedTelemetry(
        unavailable_telemetry.metrics,
        SourceResult(SourceStatus.UNAVAILABLE, LogFeatures()),
        unavailable_telemetry.traces,
    )
    degraded = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, partial
    )
    assert degraded.confidence < complete.confidence

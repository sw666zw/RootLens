"""Concurrent collection orchestration and deterministic report construction."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from rootlens_diagnosis.config import DiagnosisConfig
from rootlens_diagnosis.extractors.logs import extract_logs
from rootlens_diagnosis.extractors.metrics import extract_metrics
from rootlens_diagnosis.extractors.traces import extract_traces
from rootlens_diagnosis.incident_context import AnalysisWindow, IncidentAnalysisContext
from rootlens_diagnosis.models import (
    DiagnosisReport,
    Evidence,
    EvidenceSeverity,
    EvidenceSource,
    InputContextSummary,
    RootCause,
    SourceStatus,
    TelemetryCoverage,
)
from rootlens_diagnosis.rules import RuleDecision, diagnose
from rootlens_diagnosis.scoring import confidence_level
from rootlens_diagnosis.telemetry.jaeger import JaegerClient
from rootlens_diagnosis.telemetry.loki import LokiClient
from rootlens_diagnosis.telemetry.models import (
    LogFeatures,
    MetricsFeatures,
    NormalizedTelemetry,
    SourceResult,
    TraceFeatures,
)
from rootlens_diagnosis.telemetry.prometheus import PrometheusClient


async def collect_telemetry(
    config: DiagnosisConfig,
    window: AnalysisWindow,
    context: IncidentAnalysisContext,
) -> NormalizedTelemetry:
    """Collect independent sources concurrently with reusable clients."""
    timeout = httpx.Timeout(config.timeout_seconds)
    async with (
        httpx.AsyncClient(
            base_url=config.prometheus_url, timeout=timeout
        ) as prometheus_http,
        httpx.AsyncClient(base_url=config.loki_url, timeout=timeout) as loki_http,
        httpx.AsyncClient(base_url=config.jaeger_url, timeout=timeout) as jaeger_http,
    ):
        prometheus_task = PrometheusClient(prometheus_http).collect(window)
        loki_task = LokiClient(loki_http).collect(window, context)
        jaeger_task = JaegerClient(jaeger_http).collect(context.trace_ids, window)
        metrics_raw, logs_raw, traces_raw = await asyncio.gather(
            prometheus_task, loki_task, jaeger_task
        )
    return NormalizedTelemetry(
        metrics=SourceResult(
            metrics_raw.status,
            extract_metrics(metrics_raw.data),
            metrics_raw.warnings,
        ),
        logs=SourceResult(
            logs_raw.status,
            extract_logs(logs_raw.data),
            logs_raw.warnings,
        ),
        traces=SourceResult(
            traces_raw.status,
            extract_traces(traces_raw.data),
            traces_raw.warnings,
        ),
    )


class DiagnosisEngine:
    """Analyze normalized telemetry without access to ground truth."""

    def analyze(
        self,
        context: IncidentAnalysisContext,
        window: AnalysisWindow,
        telemetry: NormalizedTelemetry,
        *,
        diagnosis_id: str | None = None,
        generated_at: datetime | None = None,
    ) -> DiagnosisReport:
        coverage = TelemetryCoverage(
            metrics=telemetry.metrics.status,
            logs=telemetry.logs.status,
            traces=telemetry.traces.status,
        )
        all_unavailable = coverage.available_source_count() == 0
        decision = diagnose(telemetry, coverage)
        root_cause = RootCause.UNKNOWN if all_unavailable else decision.root_cause
        confidence_value = (
            0.0 if root_cause is RootCause.UNKNOWN else decision.confidence
        )
        warnings = sorted(
            {
                *telemetry.metrics.warnings,
                *telemetry.logs.warnings,
                *telemetry.traces.warnings,
                *(
                    ["All telemetry sources are unavailable; no diagnosis was inferred"]
                    if all_unavailable
                    else []
                ),
                *(
                    ["Evidence did not meet the deterministic decision threshold"]
                    if root_cause is RootCause.UNKNOWN and not all_unavailable
                    else []
                ),
            }
        )
        evidence = _all_evidence(telemetry)
        evidence.extend(_rule_evidence(decision, root_cause, telemetry))
        evidence.sort(key=lambda item: (item.source.value, item.signal, item.reference))
        alternatives = [
            cause
            for cause, _ in sorted(
                decision.scores.items(),
                key=lambda item: (-item[1].score, item[0].value),
            )
            if cause not in {root_cause, RootCause.UNKNOWN}
        ][:2]
        return DiagnosisReport(
            diagnosis_id=diagnosis_id or f"diagnosis-{uuid4().hex}",
            generated_at=(generated_at or datetime.now(UTC)).astimezone(UTC),
            analyzed_window=window,
            input_context=InputContextSummary(
                total_requests=context.total_requests,
                request_id_count=len(context.request_ids),
                trace_id_count=len(context.trace_ids),
            ),
            suspected_root_cause=root_cause,
            affected_service=(
                "inventory"
                if root_cause
                in {
                    RootCause.INVENTORY_RESERVATION_LATENCY,
                    RootCause.INVENTORY_SERVICE_UNAVAILABLE,
                }
                else None
            ),
            confidence=confidence_value,
            confidence_level=confidence_level(confidence_value),
            summary=_summary(root_cause),
            candidate_scores=decision.scores,
            evidence=evidence,
            alternative_causes=alternatives,
            telemetry_coverage=coverage,
            warnings=warnings,
            recommended_checks=_recommended_checks(root_cause),
        )


def empty_telemetry(
    status: SourceStatus = SourceStatus.UNAVAILABLE,
) -> NormalizedTelemetry:
    """Construct explicit missing telemetry for controlled failure handling/tests."""
    return NormalizedTelemetry(
        SourceResult(status, MetricsFeatures()),
        SourceResult(status, LogFeatures()),
        SourceResult(status, TraceFeatures()),
    )


def _all_evidence(telemetry: NormalizedTelemetry) -> list[Evidence]:
    evidence = [
        *telemetry.metrics.data.evidence,
        *telemetry.logs.data.evidence,
        *telemetry.traces.data.evidence,
    ]
    return sorted(
        evidence,
        key=lambda item: (item.source.value, item.signal, item.reference),
    )


def _rule_evidence(
    decision: RuleDecision,
    root_cause: RootCause,
    telemetry: NormalizedTelemetry,
) -> list[Evidence]:
    """Expose the selected rule's safe supporting and contradicting matches."""
    if root_cause is RootCause.UNKNOWN:
        return []
    score = decision.scores[root_cause]
    evidence: list[Evidence] = []
    for severity, references in (
        (EvidenceSeverity.SUPPORTING, score.supporting_evidence),
        (EvidenceSeverity.CONTRADICTING, score.contradicting_evidence),
    ):
        for reference in references:
            source_name, _, signal = reference.partition(":")
            safe_reference = _safe_rule_reference(source_name, signal, telemetry)
            if safe_reference is None:
                continue
            evidence.append(
                Evidence(
                    source=EvidenceSource(source_name),
                    signal=f"rule_{signal}",
                    observation=(
                        f"Deterministic rule matched {signal.replace('_', ' ')}"
                    ),
                    severity=severity,
                    reference=safe_reference,
                )
            )
    return evidence


def _safe_rule_reference(
    source_name: str,
    signal: str,
    telemetry: NormalizedTelemetry,
) -> str | None:
    """Map rule matches to query names, log categories, or an exact trace ID."""
    metric_queries = {
        "confirmed_orders": "order_creations",
        "low_order_success_ratio": "order_creations",
        "orders_still_succeed": "order_creations",
        "low_order_5xx_ratio": "order_requests",
        "elevated_order_5xx_ratio": "order_requests",
        "low_inventory_5xx_ratio": "inventory_requests",
        "elevated_inventory_5xx_ratio": "inventory_requests",
        "high_order_503_ratio": "order_requests",
        "low_order_503_ratio": "order_requests",
        "high_inventory_503_ratio": "inventory_requests",
        "low_inventory_503_ratio": "inventory_requests",
        "normal_order_latency": "order_p95",
        "elevated_order_latency": "order_p95",
        "normal_inventory_latency": "inventory_p95",
        "elevated_inventory_latency": "inventory_p95",
        "order_service_available": "order_up",
        "order_service_unavailable": "order_up",
        "inventory_service_available": "inventory_up",
        "inventory_service_unavailable": "inventory_up",
        "errors_remain_low": "order_errors",
        "failed_reservations": "inventory_reservations",
    }
    if source_name == "metrics":
        return metric_queries.get(signal)
    if source_name == "logs":
        return {
            "inventory_unavailable": "order_creation_failed",
            "reservations_succeeded": "inventory_reservation_succeeded",
        }.get(signal, signal)
    if source_name == "traces" and telemetry.traces.data.trace_ids:
        return telemetry.traces.data.trace_ids[0]
    return None


def _summary(cause: RootCause) -> str:
    return {
        RootCause.NONE: (
            "Telemetry is consistent with healthy Order and Inventory behavior."
        ),
        RootCause.INVENTORY_RESERVATION_LATENCY: (
            "Inventory reservation work is the dominant elevated-latency segment."
        ),
        RootCause.INVENTORY_SERVICE_UNAVAILABLE: (
            "Inventory unavailability is producing downstream Order failures."
        ),
        RootCause.UNKNOWN: (
            "Available telemetry is insufficient or conflicting for a supported "
            "diagnosis."
        ),
    }[cause]


def _recommended_checks(cause: RootCause) -> list[str]:
    checks = {
        RootCause.NONE: [
            "Confirm Order and Inventory 5xx metrics remain low outside the incident "
            "window.",
            "Sample correlated successful reservation traces in Jaeger.",
        ],
        RootCause.INVENTORY_RESERVATION_LATENCY: [
            "Inspect Inventory reservation server spans in Jaeger.",
            "Compare Order client latency with Inventory server latency.",
            "Check whether PostgreSQL spans dominate the slow trace segment.",
        ],
        RootCause.INVENTORY_SERVICE_UNAVAILABLE: [
            "Verify Inventory readiness and service-up metrics.",
            "Inspect Inventory 5xx metrics and correlated 503 completion logs.",
            "Check whether failed Inventory traces reached PostgreSQL.",
        ],
        RootCause.UNKNOWN: [
            "Restore missing telemetry sources and repeat analysis on the same window.",
            "Inspect the highest-scoring alternative and its contradicting evidence.",
        ],
    }
    return checks[cause]

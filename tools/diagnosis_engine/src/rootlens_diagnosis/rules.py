"""Transparent deterministic diagnosis rules for the first incident catalog."""

import math
from dataclasses import dataclass

from rootlens_diagnosis.models import (
    CandidateScore,
    EvidenceSource,
    RootCause,
    TelemetryCoverage,
)
from rootlens_diagnosis.scoring import ScoreBuilder, confidence
from rootlens_diagnosis.telemetry.models import NormalizedTelemetry

HEALTHY_SUCCESS_RATIO = 0.90
LOW_ERROR_RATIO = 0.05
HIGH_UNAVAILABLE_RATIO = 0.50
LATENCY_THRESHOLD_MS = 750.0
MINIMUM_CANDIDATE_SCORE = 0.45
MINIMUM_WINNING_MARGIN = 0.08


@dataclass(frozen=True)
class RuleDecision:
    root_cause: RootCause
    scores: dict[RootCause, CandidateScore]
    confidence: float
    supporting_sources: frozenset[EvidenceSource]


def diagnose(
    telemetry: NormalizedTelemetry, coverage: TelemetryCoverage
) -> RuleDecision:
    builders = {
        RootCause.NONE: _score_none(telemetry),
        RootCause.INVENTORY_RESERVATION_LATENCY: _score_latency(telemetry),
        RootCause.INVENTORY_SERVICE_UNAVAILABLE: _score_unavailable(telemetry),
    }
    scores = {cause: builder.build() for cause, builder in builders.items()}
    scores[RootCause.UNKNOWN] = CandidateScore(score=0.0)
    ranking = sorted(
        builders,
        key=lambda cause: (-scores[cause].score, cause.value),
    )
    winner, runner_up = ranking[:2]
    winning_score = scores[winner].score
    margin = winning_score - scores[runner_up].score
    if winning_score < MINIMUM_CANDIDATE_SCORE or margin < MINIMUM_WINNING_MARGIN:
        return RuleDecision(RootCause.UNKNOWN, scores, 0.0, frozenset())
    sources = frozenset(builders[winner].sources)
    return RuleDecision(
        winner,
        scores,
        confidence(winning_score, margin, len(sources), coverage),
        sources,
    )


def _score_none(telemetry: NormalizedTelemetry) -> ScoreBuilder:
    score = ScoreBuilder()
    metrics, logs, traces = (
        telemetry.metrics.data,
        telemetry.logs.data,
        telemetry.traces.data,
    )
    success_ratio = _ratio(metrics.order_confirmed, metrics.order_requests)
    order_error_ratio = _ratio(metrics.order_5xx, metrics.order_requests)
    inventory_error_ratio = _ratio(metrics.inventory_5xx, metrics.inventory_requests)
    if success_ratio is not None:
        if success_ratio >= HEALTHY_SUCCESS_RATIO:
            score.support(0.20, "metrics:confirmed_orders", EvidenceSource.METRICS)
        else:
            score.contradict(0.25, "metrics:low_order_success_ratio")
    if order_error_ratio is not None:
        if order_error_ratio <= LOW_ERROR_RATIO:
            score.support(0.10, "metrics:low_order_5xx_ratio", EvidenceSource.METRICS)
        else:
            score.contradict(0.30, "metrics:elevated_order_5xx_ratio")
    if inventory_error_ratio is not None:
        if inventory_error_ratio <= LOW_ERROR_RATIO:
            score.support(
                0.10, "metrics:low_inventory_5xx_ratio", EvidenceSource.METRICS
            )
        else:
            score.contradict(0.25, "metrics:elevated_inventory_5xx_ratio")
    _score_availability(score, "order", metrics.order_up_ratio, EvidenceSource.METRICS)
    _score_availability(
        score, "inventory", metrics.inventory_up_ratio, EvidenceSource.METRICS
    )
    _score_healthy_latency(score, "order", metrics.order_p95_ms, EvidenceSource.METRICS)
    _score_healthy_latency(
        score, "inventory", metrics.inventory_p95_ms, EvidenceSource.METRICS
    )
    _score_healthy_latency(
        score, "order", traces.order_server_p95_ms, EvidenceSource.TRACES
    )
    _score_healthy_latency(
        score, "inventory", traces.inventory_server_p95_ms, EvidenceSource.TRACES
    )
    if logs.categories.get("order_creation_succeeded", 0) > 0:
        score.support(0.15, "logs:order_creation_succeeded", EvidenceSource.LOGS)
    if logs.categories.get("order_creation_failed", 0) > 0:
        score.contradict(0.25, "logs:order_creation_failed")
    if traces.successful_reservations > 0:
        score.support(0.15, "traces:successful_reservations", EvidenceSource.TRACES)
    if traces.error_span_count == 0 and traces.trace_count > 0:
        score.support(0.10, "traces:no_error_spans", EvidenceSource.TRACES)
    elif traces.error_span_count > 0:
        score.contradict(0.20, "traces:error_spans")
    return score


def _score_latency(telemetry: NormalizedTelemetry) -> ScoreBuilder:
    score = ScoreBuilder()
    metrics, logs, traces = (
        telemetry.metrics.data,
        telemetry.logs.data,
        telemetry.traces.data,
    )
    success_ratio = _ratio(metrics.order_confirmed, metrics.order_requests)
    error_ratio = _ratio(metrics.order_5xx, metrics.order_requests)
    if success_ratio is not None:
        if success_ratio >= HEALTHY_SUCCESS_RATIO:
            score.support(0.12, "metrics:orders_still_succeed", EvidenceSource.METRICS)
        else:
            score.contradict(0.15, "metrics:low_order_success_ratio")
    if error_ratio is not None and error_ratio <= LOW_ERROR_RATIO:
        score.support(0.08, "metrics:errors_remain_low", EvidenceSource.METRICS)
    if _above(metrics.order_p95_ms, LATENCY_THRESHOLD_MS):
        score.support(0.18, "metrics:elevated_order_latency", EvidenceSource.METRICS)
    elif _known(metrics.order_p95_ms):
        score.contradict(0.15, "metrics:normal_order_latency")
    if _above(metrics.inventory_p95_ms, LATENCY_THRESHOLD_MS):
        score.support(
            0.22, "metrics:elevated_inventory_latency", EvidenceSource.METRICS
        )
    elif _known(metrics.inventory_p95_ms):
        score.contradict(0.20, "metrics:normal_inventory_latency")
    if logs.categories.get("inventory_reservation_succeeded", 0) > 0:
        score.support(0.10, "logs:reservations_succeeded", EvidenceSource.LOGS)
    if logs.categories.get("order_creation_failed", 0) > 0:
        score.contradict(0.20, "logs:order_creation_failed")
    if _above(traces.inventory_server_p95_ms, LATENCY_THRESHOLD_MS):
        score.support(
            0.22, "traces:elevated_inventory_server_latency", EvidenceSource.TRACES
        )
    elif _known(traces.inventory_server_p95_ms):
        score.contradict(0.15, "traces:normal_inventory_server_latency")
    if _above(traces.order_inventory_client_p95_ms, LATENCY_THRESHOLD_MS):
        score.support(
            0.15,
            "traces:elevated_order_inventory_client_latency",
            EvidenceSource.TRACES,
        )
    elif _known(traces.order_inventory_client_p95_ms):
        score.contradict(0.10, "traces:normal_order_inventory_client_latency")
    if traces.slowest_service == "inventory":
        score.support(0.10, "traces:inventory_slowest_service", EvidenceSource.TRACES)
    if traces.slowest_span_category == "database":
        score.contradict(0.15, "traces:database_dominant")
    return score


def _score_unavailable(telemetry: NormalizedTelemetry) -> ScoreBuilder:
    score = ScoreBuilder()
    metrics, logs, traces = (
        telemetry.metrics.data,
        telemetry.logs.data,
        telemetry.traces.data,
    )
    order_503_ratio = _ratio(metrics.order_503, metrics.order_requests)
    inventory_503_ratio = _ratio(metrics.inventory_503, metrics.inventory_requests)
    if order_503_ratio is not None:
        if order_503_ratio >= HIGH_UNAVAILABLE_RATIO:
            score.support(0.25, "metrics:high_order_503_ratio", EvidenceSource.METRICS)
        elif order_503_ratio <= LOW_ERROR_RATIO:
            score.contradict(0.25, "metrics:low_order_503_ratio")
    if inventory_503_ratio is not None:
        if inventory_503_ratio >= HIGH_UNAVAILABLE_RATIO:
            score.support(
                0.20, "metrics:high_inventory_503_ratio", EvidenceSource.METRICS
            )
        elif inventory_503_ratio <= LOW_ERROR_RATIO:
            score.contradict(0.20, "metrics:low_inventory_503_ratio")
    if metrics.reservation_failed is not None and metrics.reservation_failed > 0:
        score.support(0.10, "metrics:failed_reservations", EvidenceSource.METRICS)
    if logs.reasons.get("inventory_unavailable", 0) > 0:
        score.support(0.20, "logs:inventory_unavailable", EvidenceSource.LOGS)
    if logs.categories.get("order_creation_failed", 0) > 0:
        score.support(0.10, "logs:order_creation_failed", EvidenceSource.LOGS)
    if logs.categories.get("order_creation_succeeded", 0) > 0:
        score.contradict(0.10, "logs:order_creation_succeeded")
    if traces.failed_inventory_traces > 0:
        score.support(0.15, "traces:inventory_failures", EvidenceSource.TRACES)
    if traces.failed_without_database > 0:
        score.support(0.15, "traces:failure_before_database", EvidenceSource.TRACES)
    if traces.successful_reservations > 0 and traces.failed_inventory_traces == 0:
        score.contradict(0.15, "traces:successful_inventory_reservations")
    return score


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if not _known(numerator) or not _known(denominator) or denominator <= 0:
        return None
    ratio = numerator / denominator
    return ratio if math.isfinite(ratio) else None


def _above(value: float | None, threshold: float) -> bool:
    return _known(value) and value >= threshold


def _known(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _score_availability(
    score: ScoreBuilder,
    service: str,
    value: float | None,
    source: EvidenceSource,
) -> None:
    if not _known(value):
        return
    if value >= 0.9:
        score.support(0.075, f"metrics:{service}_service_available", source)
    elif value < 0.5:
        score.contradict(0.20, f"metrics:{service}_service_unavailable")


def _score_healthy_latency(
    score: ScoreBuilder,
    service: str,
    value: float | None,
    source: EvidenceSource,
) -> None:
    if not _known(value):
        return
    if value < LATENCY_THRESHOLD_MS:
        score.support(0.075, f"{source.value}:normal_{service}_latency", source)
    else:
        score.contradict(0.25, f"{source.value}:elevated_{service}_latency")

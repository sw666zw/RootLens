"""Application-owned bounded Prometheus collectors."""

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Histogram


@dataclass(frozen=True)
class DiagnosisMetrics:
    registry: CollectorRegistry
    http_requests: Counter
    http_duration: Histogram
    http_errors: Counter
    diagnosis_runs: Counter
    explanation_runs: Counter


def create_metrics() -> DiagnosisMetrics:
    registry = CollectorRegistry()
    return DiagnosisMetrics(
        registry,
        Counter(
            "rootlens_diagnosis_http_requests_total",
            "Completed Diagnosis Service HTTP requests.",
            ("method", "route", "status_code"),
            registry=registry,
        ),
        Histogram(
            "rootlens_diagnosis_http_request_duration_seconds",
            "Diagnosis Service HTTP request duration.",
            ("method", "route"),
            registry=registry,
        ),
        Counter(
            "rootlens_diagnosis_http_errors_total",
            "Diagnosis Service HTTP error responses.",
            ("method", "route", "status_code"),
            registry=registry,
        ),
        Counter(
            "rootlens_diagnosis_runs_total",
            "Diagnosis runs by bounded outcome and root cause.",
            ("outcome", "root_cause"),
            registry=registry,
        ),
        Counter(
            "rootlens_explanation_runs_total",
            "Explanation runs by provider and status.",
            ("provider", "status"),
            registry=registry,
        ),
    )

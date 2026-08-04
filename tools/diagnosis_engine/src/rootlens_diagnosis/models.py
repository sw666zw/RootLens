"""Typed diagnosis, scoring, and report models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from rootlens_diagnosis.incident_context import AnalysisWindow


class RootCause(StrEnum):
    NONE = "none"
    INVENTORY_RESERVATION_LATENCY = "inventory_reservation_latency"
    INVENTORY_SERVICE_UNAVAILABLE = "inventory_service_unavailable"
    UNKNOWN = "unknown"


class EvidenceSource(StrEnum):
    METRICS = "metrics"
    LOGS = "logs"
    TRACES = "traces"


class EvidenceSeverity(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    INFORMATIONAL = "informational"


class SourceStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: EvidenceSource
    signal: str
    observation: str
    value: float | None = None
    unit: str | None = None
    service: str | None = None
    severity: EvidenceSeverity = EvidenceSeverity.INFORMATIONAL
    reference: str


class CandidateScore(BaseModel):
    score: float = Field(ge=0, le=1)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)


class TelemetryCoverage(BaseModel):
    metrics: SourceStatus
    logs: SourceStatus
    traces: SourceStatus

    def available_source_count(self) -> int:
        return sum(
            status is not SourceStatus.UNAVAILABLE
            for status in (self.metrics, self.logs, self.traces)
        )


class InputContextSummary(BaseModel):
    total_requests: int
    request_id_count: int
    trace_id_count: int


class DiagnosisReport(BaseModel):
    schema_version: str = "1.0"
    diagnosis_id: str
    generated_at: datetime
    analyzed_window: AnalysisWindow
    input_context: InputContextSummary
    suspected_root_cause: RootCause
    affected_service: str | None
    confidence: float = Field(ge=0, le=1)
    confidence_level: str
    summary: str
    candidate_scores: dict[RootCause, CandidateScore]
    evidence: list[Evidence]
    alternative_causes: list[RootCause]
    telemetry_coverage: TelemetryCoverage
    warnings: list[str]
    recommended_checks: list[str]


class EvaluationReport(BaseModel):
    schema_version: str = "1.0"
    evaluation_id: str
    diagnosis_id: str
    evaluated_at: datetime
    predicted_root_cause: RootCause
    expected_root_cause: str
    exact_match: bool
    confidence: float
    telemetry_coverage: TelemetryCoverage
    evidence_source_count: int

"""Strict models for safe explanation inputs, narratives, and reports."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rootlens_diagnosis.incident_context import AnalysisWindow
from rootlens_diagnosis.models import (
    CandidateScore,
    EvidenceSeverity,
    EvidenceSource,
    InputContextSummary,
    RootCause,
    TelemetryCoverage,
)

EVIDENCE_ID_PATTERN = re.compile(r"^evidence-[0-9]{3,}$")
URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
UNSAFE_COMMAND_PATTERN = re.compile(
    r"(?:```|\b(?:DROP|DELETE|TRUNCATE|ALTER|INSERT|UPDATE)\s+"
    r"|(?:^|\s)(?:sudo\s+|rm\s+-|kubectl\s+(?:apply|delete)|"
    r"docker\s+(?:rm|stop)|systemctl\s+(?:stop|restart)))",
    re.IGNORECASE,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SafeEvidence(StrictModel):
    evidence_id: str
    source: EvidenceSource
    signal: str
    observation: str
    value: float | None = None
    unit: str | None = None
    service: str | None = None
    severity: EvidenceSeverity

    @field_validator("evidence_id")
    @classmethod
    def validate_evidence_id(cls, value: str) -> str:
        if not EVIDENCE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid evidence ID")
        return value


class SafeExplanationInput(StrictModel):
    """Explicit allowlist projection supplied to an explanation provider."""

    diagnosis_id: str
    suspected_root_cause: RootCause
    affected_service: str | None
    confidence: float = Field(ge=0, le=1)
    confidence_level: str
    deterministic_summary: str
    candidate_scores: dict[RootCause, CandidateScore]
    evidence: list[SafeEvidence]
    alternative_causes: list[RootCause]
    telemetry_coverage: TelemetryCoverage
    warnings: list[str]
    recommended_checks: list[str]
    analyzed_window: AnalysisWindow
    input_context: InputContextSummary


def _validate_narrative_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("narrative text must not be empty")
    if URL_PATTERN.search(normalized):
        raise ValueError("narrative text must not contain URLs")
    if UNSAFE_COMMAND_PATTERN.search(normalized):
        raise ValueError("narrative text contains an unsafe command")
    return normalized


class EvidenceBasedClaim(StrictModel):
    claim: str
    evidence_refs: list[str] = Field(min_length=1)

    @field_validator("claim")
    @classmethod
    def validate_claim(cls, value: str) -> str:
        return _validate_narrative_text(value)

    @field_validator("evidence_refs")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(values))
        if not normalized or any(
            not EVIDENCE_ID_PATTERN.fullmatch(value) for value in normalized
        ):
            raise ValueError("claim evidence references are invalid")
        return normalized


class ExplanationNarrative(StrictModel):
    """Provider-generated fields; deterministic diagnosis fields are forbidden."""

    headline: str
    executive_summary: str
    impact: str
    causal_chain: list[str] = Field(min_length=1)
    evidence_based_claims: list[EvidenceBasedClaim]
    uncertainties: list[str]
    immediate_actions: list[str] = Field(min_length=1)
    follow_up_actions: list[str] = Field(min_length=1)
    operator_notes: str | None = None

    @field_validator("headline", "executive_summary", "impact")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_narrative_text(value)

    @field_validator(
        "causal_chain", "uncertainties", "immediate_actions", "follow_up_actions"
    )
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        return [_validate_narrative_text(value) for value in values]

    @field_validator("operator_notes")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _validate_narrative_text(value) if value is not None else None


class ProviderUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ProviderMetadata(StrictModel):
    provider: Literal["template", "openai"]
    model: str | None = None
    response_id: str | None = None
    usage: ProviderUsage | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class ProviderResult(StrictModel):
    narrative: ExplanationNarrative
    metadata: ProviderMetadata
    warnings: list[str] = Field(default_factory=list)


class ProviderStatus(StrEnum):
    COMPLETED = "completed"
    FALLBACK = "fallback"


class ExplanationValidationSummary(StrictModel):
    protected_fields_match: bool
    evidence_references_valid: bool
    required_fields_present: bool
    no_ground_truth_fields: bool
    overall_valid: bool


class ExplanationReport(StrictModel):
    schema_version: str = "1.0"
    explanation_id: str
    generated_at: datetime
    diagnosis_id: str
    suspected_root_cause: RootCause
    affected_service: str | None
    confidence: float = Field(ge=0, le=1)
    confidence_level: str
    telemetry_coverage: TelemetryCoverage
    provider: Literal["template", "openai"]
    provider_status: ProviderStatus
    model: str | None = None
    provider_response_id: str | None = None
    provider_usage: ProviderUsage | None = None
    provider_latency_ms: int | None = Field(default=None, ge=0)
    headline: str
    executive_summary: str
    impact: str
    causal_chain: list[str] = Field(min_length=1)
    evidence_based_claims: list[EvidenceBasedClaim]
    evidence_index: list[SafeEvidence]
    uncertainties: list[str]
    immediate_actions: list[str] = Field(min_length=1)
    follow_up_actions: list[str] = Field(min_length=1)
    operator_notes: str | None = None
    validation: ExplanationValidationSummary
    warnings: list[str]

    @field_validator("headline", "executive_summary", "impact")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _validate_narrative_text(value)

    @field_validator(
        "causal_chain", "uncertainties", "immediate_actions", "follow_up_actions"
    )
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        return [_validate_narrative_text(value) for value in values]

    @field_validator("operator_notes")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _validate_narrative_text(value) if value is not None else None


class ExplanationValidationReport(StrictModel):
    schema_version: str = "1.0"
    validation_id: str
    validated_at: datetime
    explanation_id: str | None
    diagnosis_id: str | None
    protected_fields_match: bool
    evidence_references_valid: bool
    required_fields_present: bool
    no_ground_truth_fields: bool
    provider_status_valid: bool
    no_credentials: bool
    evidence_index_matches: bool
    overall_valid: bool
    errors: list[str]


def model_contains_forbidden_key(payload: Any, forbidden: set[str]) -> bool:
    if isinstance(payload, dict):
        return any(
            str(key).lower() in forbidden
            or model_contains_forbidden_key(value, forbidden)
            for key, value in payload.items()
        )
    if isinstance(payload, list):
        return any(model_contains_forbidden_key(value, forbidden) for value in payload)
    return False

"""Explanation API schemas."""

from pydantic import BaseModel
from rootlens_diagnosis.explanation_models import (
    ExplanationValidationSummary,
    ProviderStatus,
)


class ExplainRequest(BaseModel):
    provider: str | None = None
    allow_template_fallback: bool = False


class ExplanationResponse(BaseModel):
    explanation_id: str
    diagnosis_id: str
    provider: str
    provider_status: ProviderStatus
    model: str | None
    headline: str
    executive_summary: str
    confidence: float
    validation: ExplanationValidationSummary
    warnings: list[str]
    report_url: str


class ExplanationSummary(BaseModel):
    explanation_id: str
    diagnosis_id: str
    generated_at: str
    provider: str
    provider_status: ProviderStatus
    model: str | None
    headline: str
    confidence: float


class ValidateExplanationRequest(BaseModel):
    diagnosis_id: str


class ValidationResponse(BaseModel):
    overall_valid: bool
    protected_fields_match: bool
    evidence_references_valid: bool
    required_fields_present: bool
    no_ground_truth_fields: bool
    validation_report_id: str

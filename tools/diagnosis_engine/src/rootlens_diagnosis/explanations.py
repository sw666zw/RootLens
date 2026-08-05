"""Explanation orchestration that preserves deterministic diagnosis authority."""

from datetime import UTC, datetime
from uuid import uuid4

from rootlens_diagnosis.explanation_models import (
    ExplanationReport,
    ExplanationValidationSummary,
    ProviderResult,
    ProviderStatus,
    SafeExplanationInput,
)
from rootlens_diagnosis.explanation_providers import ExplanationProvider
from rootlens_diagnosis.explanation_validation import (
    contains_credentials,
    validation_summary,
)
from rootlens_diagnosis.models import DiagnosisReport


def create_explanation_report(
    diagnosis: DiagnosisReport,
    projection: SafeExplanationInput,
    provider_result: ProviderResult,
    *,
    provider_status: ProviderStatus = ProviderStatus.COMPLETED,
    explanation_id: str | None = None,
    generated_at: datetime | None = None,
    extra_warnings: list[str] | None = None,
) -> ExplanationReport:
    """Assemble protected fields in application code, never from provider output."""
    narrative = provider_result.narrative
    metadata = provider_result.metadata
    if provider_status is ProviderStatus.FALLBACK and metadata.provider != "template":
        raise ValueError("fallback explanations must use the template provider")
    placeholder = ExplanationValidationSummary(
        protected_fields_match=False,
        evidence_references_valid=False,
        required_fields_present=False,
        no_ground_truth_fields=False,
        overall_valid=False,
    )
    report = ExplanationReport(
        explanation_id=explanation_id or f"explanation-{uuid4().hex}",
        generated_at=(generated_at or datetime.now(UTC)).astimezone(UTC),
        diagnosis_id=diagnosis.diagnosis_id,
        suspected_root_cause=diagnosis.suspected_root_cause,
        affected_service=diagnosis.affected_service,
        confidence=diagnosis.confidence,
        confidence_level=diagnosis.confidence_level,
        telemetry_coverage=diagnosis.telemetry_coverage,
        provider=metadata.provider,
        provider_status=provider_status,
        model=metadata.model,
        provider_response_id=metadata.response_id,
        provider_usage=metadata.usage,
        provider_latency_ms=metadata.latency_ms,
        headline=narrative.headline,
        executive_summary=narrative.executive_summary,
        impact=narrative.impact,
        causal_chain=narrative.causal_chain,
        evidence_based_claims=narrative.evidence_based_claims,
        evidence_index=projection.evidence,
        uncertainties=narrative.uncertainties,
        immediate_actions=narrative.immediate_actions,
        follow_up_actions=narrative.follow_up_actions,
        operator_notes=narrative.operator_notes,
        validation=placeholder,
        warnings=list(
            dict.fromkeys(
                [
                    *diagnosis.warnings,
                    *provider_result.warnings,
                    *(extra_warnings or []),
                ]
            )
        ),
    )
    summary = validation_summary(report, diagnosis)
    if not summary.overall_valid or contains_credentials(
        report.model_dump(mode="json")
    ):
        raise ValueError("explanation failed application validation")
    return report.model_copy(update={"validation": summary})


def generate_with_provider(
    provider: ExplanationProvider, projection: SafeExplanationInput
) -> ProviderResult:
    """Narrow seam for CLI orchestration and provider test doubles."""
    return provider.generate(projection)

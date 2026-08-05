"""Safe typed projection from deterministic diagnosis to provider input."""

from rootlens_diagnosis.explanation_models import SafeEvidence, SafeExplanationInput
from rootlens_diagnosis.models import DiagnosisReport


def build_safe_explanation_input(report: DiagnosisReport) -> SafeExplanationInput:
    """Copy only explicitly authorized normalized diagnosis fields."""
    evidence = [
        SafeEvidence(
            evidence_id=f"evidence-{index:03d}",
            source=item.source,
            signal=item.signal,
            observation=item.observation,
            value=item.value,
            unit=item.unit,
            service=item.service,
            severity=item.severity,
        )
        for index, item in enumerate(report.evidence, start=1)
    ]
    return SafeExplanationInput(
        diagnosis_id=report.diagnosis_id,
        suspected_root_cause=report.suspected_root_cause,
        affected_service=report.affected_service,
        confidence=report.confidence,
        confidence_level=report.confidence_level,
        deterministic_summary=report.summary,
        candidate_scores=report.candidate_scores,
        evidence=evidence,
        alternative_causes=report.alternative_causes,
        telemetry_coverage=report.telemetry_coverage,
        warnings=report.warnings,
        recommended_checks=report.recommended_checks,
        analyzed_window=report.analyzed_window,
        input_context=report.input_context,
    )

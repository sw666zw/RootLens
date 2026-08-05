import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rootlens_diagnosis.explanation_models import ExplanationReport, ProviderStatus
from rootlens_diagnosis.explanation_projection import build_safe_explanation_input
from rootlens_diagnosis.explanation_providers import TemplateExplanationProvider
from rootlens_diagnosis.explanation_validation import validate_explanation_file
from rootlens_diagnosis.explanations import create_explanation_report
from rootlens_diagnosis.models import DiagnosisReport
from rootlens_diagnosis.reports import (
    write_diagnosis_report,
    write_explanation_report,
)


def make_explanation(diagnosis_report: DiagnosisReport) -> ExplanationReport:
    projection = build_safe_explanation_input(diagnosis_report)
    result = TemplateExplanationProvider().generate(projection)
    return create_explanation_report(
        diagnosis_report,
        projection,
        result,
        explanation_id="explanation-safe-test",
        generated_at=datetime(2026, 8, 3, 22, 0, tzinfo=UTC),
    )


def write_sources(
    tmp_path: Path, diagnosis_report: DiagnosisReport
) -> tuple[Path, Path]:
    diagnosis_path = write_diagnosis_report(diagnosis_report, tmp_path)
    explanation_path = write_explanation_report(
        make_explanation(diagnosis_report), tmp_path
    )
    return diagnosis_path, explanation_path


def test_report_copies_protected_fields_and_contains_no_secrets(
    diagnosis_report: DiagnosisReport,
) -> None:
    report = make_explanation(diagnosis_report)
    payload = report.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["diagnosis_id"] == diagnosis_report.diagnosis_id
    assert payload["suspected_root_cause"] == diagnosis_report.suspected_root_cause
    assert payload["affected_service"] == diagnosis_report.affected_service
    assert payload["confidence"] == diagnosis_report.confidence
    assert payload["confidence_level"] == diagnosis_report.confidence_level
    expected_coverage = diagnosis_report.telemetry_coverage.model_dump(mode="json")
    assert payload["telemetry_coverage"] == expected_coverage
    assert payload["provider_usage"] is None
    assert payload["validation"]["overall_valid"] is True
    assert "expected_root_cause" not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "sk-private-value" not in serialized
    assert all("reference" not in item for item in payload["evidence_index"])


def test_valid_explanation_passes_without_modifying_sources(
    tmp_path: Path, diagnosis_report: DiagnosisReport
) -> None:
    diagnosis_path, explanation_path = write_sources(tmp_path, diagnosis_report)
    before_diagnosis = diagnosis_path.read_bytes()
    before_explanation = explanation_path.read_bytes()

    result = validate_explanation_file(
        explanation_path,
        diagnosis_path,
        validation_id="validation-safe-test",
        validated_at=datetime(2026, 8, 3, 23, 0, tzinfo=UTC),
    )

    assert result.overall_valid is True
    assert result.errors == []
    assert diagnosis_path.read_bytes() == before_diagnosis
    assert explanation_path.read_bytes() == before_explanation


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("suspected_root_cause", "inventory_service_unavailable", "protected"),
        ("confidence", 0.123, "protected"),
        ("affected_service", "order", "protected"),
        ("confidence_level", "low", "protected"),
    ],
)
def test_changed_protected_fields_fail(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    field: str,
    value: object,
    error: str,
) -> None:
    diagnosis_path, explanation_path = write_sources(tmp_path, diagnosis_report)
    payload = json.loads(explanation_path.read_text(encoding="utf-8"))
    payload[field] = value
    explanation_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_explanation_file(explanation_path, diagnosis_path)

    assert result.overall_valid is False
    assert any(error in message for message in result.errors)


def test_nonexistent_empty_and_changed_evidence_fail(
    tmp_path: Path, diagnosis_report: DiagnosisReport
) -> None:
    diagnosis_path, explanation_path = write_sources(tmp_path, diagnosis_report)
    payload = json.loads(explanation_path.read_text(encoding="utf-8"))
    payload["evidence_based_claims"][0]["evidence_refs"] = ["evidence-999"]
    explanation_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not validate_explanation_file(explanation_path, diagnosis_path).overall_valid

    payload["evidence_based_claims"][0]["evidence_refs"] = []
    explanation_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not validate_explanation_file(explanation_path, diagnosis_path).overall_valid

    payload = make_explanation(diagnosis_report).model_dump(mode="json")
    payload["evidence_index"][0]["observation"] = "changed"
    explanation_path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_explanation_file(explanation_path, diagnosis_path)
    assert result.evidence_index_matches is False
    assert result.overall_valid is False


def test_missing_narrative_ground_truth_and_credentials_fail(
    tmp_path: Path, diagnosis_report: DiagnosisReport
) -> None:
    diagnosis_path, explanation_path = write_sources(tmp_path, diagnosis_report)
    payload = json.loads(explanation_path.read_text(encoding="utf-8"))
    payload["headline"] = ""
    payload["expected_root_cause"] = "secret-answer"
    payload["OPENAI_API_KEY"] = "sk-private-value"
    explanation_path.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_explanation_file(explanation_path, diagnosis_path)

    assert result.required_fields_present is False
    assert result.no_ground_truth_fields is False
    assert result.no_credentials is False
    assert result.overall_valid is False


def test_fallback_status_is_explicit_and_valid(
    tmp_path: Path, diagnosis_report: DiagnosisReport
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    report = create_explanation_report(
        diagnosis_report,
        projection,
        TemplateExplanationProvider().generate(projection),
        provider_status=ProviderStatus.FALLBACK,
        extra_warnings=["Explicit template fallback was used."],
    )
    diagnosis_path = write_diagnosis_report(diagnosis_report, tmp_path)
    explanation_path = write_explanation_report(report, tmp_path)

    result = validate_explanation_file(explanation_path, diagnosis_path)

    assert report.provider == "template"
    assert report.provider_status is ProviderStatus.FALLBACK
    assert result.provider_status_valid is True
    assert result.overall_valid is True


def test_explanation_write_is_deterministic_and_leaves_no_temp_file(
    tmp_path: Path, diagnosis_report: DiagnosisReport
) -> None:
    report = make_explanation(diagnosis_report)
    path = write_explanation_report(report, tmp_path)
    first = path.read_bytes()
    write_explanation_report(report, tmp_path)

    assert path.read_bytes() == first
    assert list(tmp_path.glob("*.tmp")) == []


def test_provider_metadata_cannot_put_api_key_in_report(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    result = (
        TemplateExplanationProvider()
        .generate(projection)
        .model_copy(update={"warnings": ["provider failed with sk-private-value"]})
    )

    with pytest.raises(ValueError, match="application validation"):
        create_explanation_report(diagnosis_report, projection, result)

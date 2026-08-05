"""Offline validation of an explanation against its deterministic diagnosis."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from rootlens_diagnosis.evaluation import load_diagnosis
from rootlens_diagnosis.explanation_models import (
    ExplanationReport,
    ExplanationValidationReport,
    ExplanationValidationSummary,
    ProviderStatus,
    model_contains_forbidden_key,
)
from rootlens_diagnosis.explanation_projection import build_safe_explanation_input
from rootlens_diagnosis.models import DiagnosisReport

GROUND_TRUTH_KEYS = {
    "expected_root_cause",
    "expected_symptoms",
    "scenario_name",
    "scenario_id",
    "incident_filename",
    "incident_report_filename",
}
CREDENTIAL_KEYS = {
    "api_key",
    "openai_api_key",
    "password",
    "secret",
    "credential",
    "credentials",
    "database_url",
}
CREDENTIAL_VALUE_PATTERN = re.compile(
    r"(?:OPENAI_API_KEY|\bsk-[A-Za-z0-9_-]{8,})", re.IGNORECASE
)


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} path must be an existing file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be readable valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def validation_summary(
    explanation: ExplanationReport, diagnosis: DiagnosisReport
) -> ExplanationValidationSummary:
    expected_evidence = build_safe_explanation_input(diagnosis).evidence
    valid_ids = {item.evidence_id for item in expected_evidence}
    protected = _protected_fields_match(explanation.model_dump(), diagnosis)
    evidence_valid = (
        _references_valid(
            [item.model_dump() for item in explanation.evidence_based_claims], valid_ids
        )
        and explanation.evidence_index == expected_evidence
    )
    required = _required_fields_present(explanation.model_dump())
    no_ground_truth = not model_contains_forbidden_key(
        explanation.model_dump(mode="json"), GROUND_TRUTH_KEYS
    )
    return ExplanationValidationSummary(
        protected_fields_match=protected,
        evidence_references_valid=evidence_valid,
        required_fields_present=required,
        no_ground_truth_fields=no_ground_truth,
        overall_valid=protected and evidence_valid and required and no_ground_truth,
    )


def contains_credentials(payload: dict[str, Any]) -> bool:
    """Detect obvious credential keys or API-key-shaped values."""
    return (
        model_contains_forbidden_key(payload, CREDENTIAL_KEYS)
        or CREDENTIAL_VALUE_PATTERN.search(
            json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        is not None
    )


def validate_explanation_file(
    explanation_path: Path,
    diagnosis_path: Path,
    *,
    validation_id: str | None = None,
    validated_at: datetime | None = None,
) -> ExplanationValidationReport:
    """Validate without invoking providers or modifying either source report."""
    diagnosis = load_diagnosis(diagnosis_path)
    raw = load_json_object(explanation_path, "explanation report")
    errors: list[str] = []
    try:
        explanation = ExplanationReport.model_validate(raw)
    except ValidationError:
        explanation = None
        errors.append("explanation report schema is invalid")

    protected = _protected_fields_match(raw, diagnosis)
    if not protected:
        errors.append("protected deterministic fields do not match")
    expected_evidence = build_safe_explanation_input(diagnosis).evidence
    expected_index = [item.model_dump(mode="json") for item in expected_evidence]
    actual_index = raw.get("evidence_index")
    evidence_index_matches = actual_index == expected_index
    if not evidence_index_matches:
        errors.append("evidence index does not match the diagnosis")
    claims = raw.get("evidence_based_claims")
    references_valid = _references_valid(
        claims,
        {item.evidence_id for item in expected_evidence},
    )
    if not references_valid:
        errors.append("evidence references are invalid")
    required = _required_fields_present(raw)
    if not required:
        errors.append("required narrative fields are missing or empty")
    no_ground_truth = not model_contains_forbidden_key(raw, GROUND_TRUTH_KEYS)
    if not no_ground_truth:
        errors.append("ground-truth fields are present")
    provider_status_valid = _provider_status_valid(raw)
    if not provider_status_valid:
        errors.append("provider status is invalid")
    no_credentials = not contains_credentials(raw)
    if not no_credentials:
        errors.append("credential material is present")
    schema_valid = explanation is not None
    overall = all(
        (
            schema_valid,
            protected,
            evidence_index_matches,
            references_valid,
            required,
            no_ground_truth,
            provider_status_valid,
            no_credentials,
        )
    )
    return ExplanationValidationReport(
        validation_id=validation_id or f"validation-{uuid4().hex}",
        validated_at=(validated_at or datetime.now(UTC)).astimezone(UTC),
        explanation_id=_optional_raw_string(raw.get("explanation_id")),
        diagnosis_id=_optional_raw_string(raw.get("diagnosis_id")),
        protected_fields_match=protected,
        evidence_references_valid=references_valid,
        required_fields_present=required,
        no_ground_truth_fields=no_ground_truth,
        provider_status_valid=provider_status_valid,
        no_credentials=no_credentials,
        evidence_index_matches=evidence_index_matches,
        overall_valid=overall,
        errors=errors,
    )


def _protected_fields_match(raw: dict[str, Any], diagnosis: DiagnosisReport) -> bool:
    expected = {
        "diagnosis_id": diagnosis.diagnosis_id,
        "suspected_root_cause": diagnosis.suspected_root_cause.value,
        "affected_service": diagnosis.affected_service,
        "confidence": diagnosis.confidence,
        "confidence_level": diagnosis.confidence_level,
        "telemetry_coverage": diagnosis.telemetry_coverage.model_dump(mode="json"),
    }
    return all(raw.get(key) == value for key, value in expected.items())


def _references_valid(claims: Any, valid_ids: set[str]) -> bool:
    if not isinstance(claims, list):
        return False
    for claim in claims:
        if not isinstance(claim, dict):
            return False
        text = claim.get("claim")
        references = claim.get("evidence_refs")
        if not isinstance(text, str) or not text.strip():
            return False
        if not isinstance(references, list) or not references:
            return False
        if any(
            not isinstance(item, str) or item not in valid_ids for item in references
        ):
            return False
    return True


def _required_fields_present(raw: dict[str, Any]) -> bool:
    for name in ("headline", "executive_summary", "impact"):
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            return False
    for name in ("causal_chain", "immediate_actions", "follow_up_actions"):
        value = raw.get(name)
        if not isinstance(value, list) or not value:
            return False
        if any(not isinstance(item, str) or not item.strip() for item in value):
            return False
    return isinstance(raw.get("uncertainties"), list) and isinstance(
        raw.get("evidence_based_claims"), list
    )


def _provider_status_valid(raw: dict[str, Any]) -> bool:
    provider = raw.get("provider")
    status = raw.get("provider_status")
    if provider not in {"template", "openai"}:
        return False
    if status == ProviderStatus.COMPLETED.value:
        return True
    return status == ProviderStatus.FALLBACK.value and provider == "template"


def _optional_raw_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None

"""Ground-truth comparison kept separate from diagnosis execution."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from rootlens_diagnosis.models import DiagnosisReport, EvaluationReport


def evaluate_existing_diagnosis(
    diagnosis_path: Path,
    incident_path: Path,
    *,
    evaluation_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> EvaluationReport:
    """Load a finished diagnosis, then read only evaluation ground truth."""
    diagnosis = _load_diagnosis(diagnosis_path)
    incident = _load_object(incident_path, "incident report")
    expected = incident.get("expected_root_cause")
    if not isinstance(expected, str) or not expected:
        raise ValueError("incident report has no valid expected_root_cause")
    return EvaluationReport(
        evaluation_id=evaluation_id or f"evaluation-{uuid4().hex}",
        diagnosis_id=diagnosis.diagnosis_id,
        evaluated_at=(evaluated_at or datetime.now(UTC)).astimezone(UTC),
        predicted_root_cause=diagnosis.suspected_root_cause,
        expected_root_cause=expected,
        exact_match=diagnosis.suspected_root_cause.value == expected,
        confidence=diagnosis.confidence,
        telemetry_coverage=diagnosis.telemetry_coverage,
        evidence_source_count=len({item.source for item in diagnosis.evidence}),
    )


def _load_diagnosis(path: Path) -> DiagnosisReport:
    try:
        return DiagnosisReport.model_validate(_load_object(path, "diagnosis report"))
    except ValidationError as error:
        raise ValueError("diagnosis report is invalid") from error


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} path must be an existing file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be readable valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload

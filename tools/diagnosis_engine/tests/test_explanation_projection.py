import json
from pathlib import Path

from rootlens_diagnosis.evaluation import load_diagnosis
from rootlens_diagnosis.explanation_projection import build_safe_explanation_input
from rootlens_diagnosis.models import DiagnosisReport


def test_projection_is_explicit_and_excludes_ground_truth_and_raw_fields(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    payload = projection.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["diagnosis_id"] == diagnosis_report.diagnosis_id
    assert payload["suspected_root_cause"] == diagnosis_report.suspected_root_cause
    assert payload["confidence"] == diagnosis_report.confidence
    assert payload["telemetry_coverage"] == (
        diagnosis_report.telemetry_coverage.model_dump(mode="json")
    )
    for forbidden in (
        "expected_root_cause",
        "expected_symptoms",
        "scenario_name",
        "scenario_id",
        "incident_filename",
        "raw_logs",
        "raw_trace",
        "prometheus_response",
        "sql",
        "request_body",
        "idempotency_key",
        "database_url",
    ):
        assert forbidden not in serialized.lower()
    assert all("reference" not in item for item in payload["evidence"])


def test_evidence_ids_are_stable_and_ordered(
    diagnosis_report: DiagnosisReport,
) -> None:
    first = build_safe_explanation_input(diagnosis_report)
    second = build_safe_explanation_input(diagnosis_report)

    assert first == second
    assert [item.evidence_id for item in first.evidence] == [
        f"evidence-{index:03d}" for index in range(1, len(first.evidence) + 1)
    ]


def test_changing_extra_ground_truth_does_not_change_input(
    tmp_path: Path, diagnosis_report: DiagnosisReport
) -> None:
    payload = diagnosis_report.model_dump(mode="json")
    first_path = tmp_path / "first-revealing-name.json"
    second_path = tmp_path / "second-revealing-name.json"
    first_path.write_text(
        json.dumps(
            {
                **payload,
                "expected_root_cause": "one-answer",
                "scenario_name": "one-scenario",
                "expected_symptoms": ["one symptom"],
            }
        ),
        encoding="utf-8",
    )
    second_path.write_text(
        json.dumps(
            {
                **payload,
                "expected_root_cause": "different-answer",
                "scenario_name": "different-scenario",
                "expected_symptoms": ["different symptom"],
            }
        ),
        encoding="utf-8",
    )

    assert build_safe_explanation_input(
        load_diagnosis(first_path)
    ) == build_safe_explanation_input(load_diagnosis(second_path))

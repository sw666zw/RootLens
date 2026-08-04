import json
from datetime import UTC, datetime
from pathlib import Path

from rootlens_diagnosis.engine import DiagnosisEngine
from rootlens_diagnosis.evaluation import evaluate_existing_diagnosis
from rootlens_diagnosis.models import RootCause
from rootlens_diagnosis.reports import write_diagnosis_report


def test_report_required_fields_atomic_and_no_ground_truth(
    tmp_path: Path,
    context: object,
    window: object,
    healthy_telemetry: object,
) -> None:
    report = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context,
        window,
        healthy_telemetry,
        diagnosis_id="diagnosis-fixed",
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    path = write_diagnosis_report(report, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["suspected_root_cause"] == "none"
    assert 0 <= payload["confidence"] <= 1
    assert payload["candidate_scores"]
    serialized = path.read_text(encoding="utf-8")
    for forbidden in (
        "expected_root_cause",
        "expected_symptoms",
        "scenario_name",
        "scenario_id",
        "target_service",
        "password",
        "db.statement",
    ):
        assert forbidden not in serialized
    assert not list(tmp_path.glob("*.tmp"))


def test_evaluation_matches_without_modifying_or_rerunning_diagnosis(
    tmp_path: Path,
    context: object,
    window: object,
    healthy_telemetry: object,
) -> None:
    report = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, healthy_telemetry, diagnosis_id="diagnosis-fixed"
    )
    diagnosis_path = write_diagnosis_report(report, tmp_path)
    before = diagnosis_path.read_bytes()
    incident = tmp_path / "incident.json"
    incident.write_text(json.dumps({"expected_root_cause": "none"}), encoding="utf-8")

    evaluation = evaluate_existing_diagnosis(
        diagnosis_path,
        incident,
        evaluation_id="evaluation-fixed",
        evaluated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert evaluation.exact_match
    assert evaluation.predicted_root_cause is RootCause.NONE
    assert diagnosis_path.read_bytes() == before


def test_evaluation_mismatch_fails_comparison(
    tmp_path: Path,
    context: object,
    window: object,
    healthy_telemetry: object,
) -> None:
    diagnosis = DiagnosisEngine().analyze(  # type: ignore[arg-type]
        context, window, healthy_telemetry
    )
    diagnosis_path = write_diagnosis_report(diagnosis, tmp_path)
    incident = tmp_path / "incident.json"
    incident.write_text(
        json.dumps({"expected_root_cause": "inventory_service_unavailable"}),
        encoding="utf-8",
    )
    assert not evaluate_existing_diagnosis(diagnosis_path, incident).exact_match

import json
from pathlib import Path

import pytest

from rootlens_diagnosis.engine import DiagnosisEngine
from rootlens_diagnosis.incident_context import (
    load_analysis_context,
    normalized_window,
)


def _incident(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scenario_id": "inventory-unavailable-secret-name",
        "scenario_name": "inventory-unavailable",
        "target_service": "inventory",
        "expected_root_cause": "inventory_service_unavailable",
        "expected_symptoms": ["secret expected symptom"],
        "started_at": "2026-08-03T20:00:00Z",
        "ended_at": "2026-08-03T20:00:20Z",
        "request_ids": ["request-1"],
        "trace_ids": ["0af7651916cd43dd8448eb211c80319c"],
        "total_requests": 1,
        "inventory_sku": "SAFE-SKU",
        "concurrency": 1,
    }
    payload.update(overrides)
    return payload


def test_projection_makes_ground_truth_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "inventory-unavailable-filename.json"
    path.write_text(json.dumps(_incident()), encoding="utf-8")

    context = load_analysis_context(path)

    assert not hasattr(context, "scenario_name")
    assert not hasattr(context, "scenario_id")
    assert not hasattr(context, "target_service")
    assert not hasattr(context, "expected_root_cause")
    assert not hasattr(context, "expected_symptoms")


def test_ground_truth_and_filename_changes_do_not_change_diagnosis(
    tmp_path: Path, healthy_telemetry: object
) -> None:
    first = tmp_path / "baseline-answer.json"
    second = tmp_path / "inventory-latency-answer.json"
    first.write_text(json.dumps(_incident()), encoding="utf-8")
    second.write_text(
        json.dumps(
            _incident(
                scenario_id="baseline-revealing-id",
                scenario_name="baseline",
                target_service="order",
                expected_root_cause="none",
                expected_symptoms=["changed"],
            )
        ),
        encoding="utf-8",
    )
    contexts = [load_analysis_context(first), load_analysis_context(second)]
    engine = DiagnosisEngine()
    reports = [
        engine.analyze(
            item,
            normalized_window(item, 15),
            healthy_telemetry,  # type: ignore[arg-type]
            diagnosis_id="fixed",
        )
        for item in contexts
    ]

    assert contexts[0] == contexts[1]
    assert reports[0].suspected_root_cause == reports[1].suspected_root_cause
    assert reports[0].candidate_scores == reports[1].candidate_scores


def test_window_is_utc_padded_and_rejects_invalid_order(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_incident()), encoding="utf-8")
    window = normalized_window(load_analysis_context(valid), 15)
    assert window.seconds == 50
    assert window.start.utcoffset().total_seconds() == 0

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(
            _incident(
                started_at="2026-08-03T20:01:00Z",
                ended_at="2026-08-03T20:00:00Z",
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not precede"):
        load_analysis_context(invalid)

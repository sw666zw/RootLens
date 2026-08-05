"""Filesystem confinement and report projection tests."""

import json
from pathlib import Path

import pytest

from diagnosis_service.repositories.report_files import (
    ReportFileRepository,
    UnsupportedReportError,
)


def incident_payload(scenario_id: str) -> dict[str, object]:
    return {"scenario_id": scenario_id}


@pytest.mark.parametrize(
    "unsafe", ["../secret", "/tmp/secret", "%2e%2e%2fsecret", "..%252fsecret"]
)
def test_repository_rejects_paths_and_encoded_traversal(tmp_path: Path, unsafe: str):
    repository = ReportFileRepository(tmp_path, "scenario_id")
    with pytest.raises(UnsupportedReportError):
        repository.get(unsafe)


def test_repository_never_reads_outside_root_and_ignores_unsupported_files(
    tmp_path: Path,
):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(incident_payload("outside")), encoding="utf-8")
    (root / "ignored.txt").write_text("{}", encoding="utf-8")
    (root / ".temporary.json.tmp").write_text("{}", encoding="utf-8")
    repository = ReportFileRepository(root, "scenario_id")
    assert repository.list(50) == []


def test_incident_api_hides_ground_truth_and_raw_ids(client):
    listing = client.get("/incidents")
    assert listing.status_code == 200
    serialized = listing.text
    assert "expected_root_cause" not in serialized
    assert "expected_symptoms" not in serialized

    detail = client.get("/incidents/baseline-20260805-abc")
    assert detail.status_code == 200
    assert detail.json()["request_id_count"] == 2
    assert "request_ids" not in detail.json()
    assert "target_service" not in detail.json()


def test_malformed_incident_returns_safe_422(client, settings):
    bad = settings.incident_output_dir / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    response = client.get("/incidents/bad")
    assert response.status_code == 422
    assert response.json() == {"detail": "The stored report is invalid."}
    assert str(settings.incident_output_dir) not in response.text


def test_missing_incident_has_exact_error(client):
    response = client.get("/incidents/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "Incident report not found."}

"""Diagnosis creation and report retrieval behavior."""

from diagnosis_service.services.diagnosis import DiagnosisTelemetryUnavailable


def test_diagnosis_uses_python_service_and_can_be_listed(
    client, fake_diagnosis, settings
):
    response = client.post(
        "/incidents/baseline-20260805-abc/diagnose",
        json={"require_all_sources": False, "window_padding_seconds": None},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["report_url"] == f"/diagnoses/{body['diagnosis_id']}"
    assert fake_diagnosis.incident_paths == [
        settings.incident_output_dir / "baseline-20260805-abc.json"
    ]
    assert "expected_root_cause" not in response.text

    listing = client.get("/diagnoses")
    assert listing.status_code == 200
    assert listing.json()[0]["diagnosis_id"] == body["diagnosis_id"]
    assert client.get(body["report_url"]).status_code == 200


def test_missing_diagnosis_has_exact_error(client):
    response = client.get("/diagnoses/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "Diagnosis report not found."}


def test_telemetry_failure_is_safe(client):
    original = client.app.state.diagnosis_service.diagnose

    async def unavailable(*args, **kwargs):
        report = await original(*args, **kwargs)
        raise DiagnosisTelemetryUnavailable(report)

    client.app.state.diagnosis_service.diagnose = unavailable
    response = client.post("/incidents/baseline-20260805-abc/diagnose", json={})
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Telemetry required for diagnosis is unavailable."
    }

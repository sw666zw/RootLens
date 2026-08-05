"""Template generation, provider safety, and offline validation."""


def _diagnose(client) -> str:
    response = client.post("/incidents/baseline-20260805-abc/diagnose", json={})
    assert response.status_code == 201
    return response.json()["diagnosis_id"]


def test_template_explanation_can_be_listed_retrieved_and_validated(client):
    diagnosis_id = _diagnose(client)
    explained = client.post(f"/diagnoses/{diagnosis_id}/explain", json={})
    assert explained.status_code == 201
    body = explained.json()
    assert body["provider"] == "template"
    assert body["provider_status"] == "completed"
    assert "provider_response_id" not in body
    assert client.get(body["report_url"]).status_code == 200
    assert (
        client.get("/explanations").json()[0]["explanation_id"]
        == body["explanation_id"]
    )

    validated = client.post(
        f"/explanations/{body['explanation_id']}/validate",
        json={"diagnosis_id": diagnosis_id},
    )
    assert validated.status_code == 200
    assert validated.json()["overall_valid"] is True


def test_openai_is_disabled_and_unsupported_provider_is_safe(client):
    diagnosis_id = _diagnose(client)
    disabled = client.post(
        f"/diagnoses/{diagnosis_id}/explain", json={"provider": "openai"}
    )
    assert disabled.status_code == 503
    assert disabled.json() == {"detail": "OpenAI explanations are not enabled."}

    unsupported = client.post(
        f"/diagnoses/{diagnosis_id}/explain", json={"provider": "other"}
    )
    assert unsupported.status_code == 400
    assert unsupported.json() == {"detail": "Unsupported explanation provider."}


def test_missing_explanation_has_exact_error(client):
    response = client.get("/explanations/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "Explanation report not found."}


def test_invalid_validation_is_422_and_preserves_both_sources(client, settings):
    import json

    diagnosis_id = _diagnose(client)
    explained = client.post(f"/diagnoses/{diagnosis_id}/explain", json={}).json()
    explanation_id = explained["explanation_id"]
    diagnosis_path = settings.diagnosis.output_dir / f"{diagnosis_id}.json"
    explanation_path = settings.explanation.output_dir / f"{explanation_id}.json"
    diagnosis_before = diagnosis_path.read_bytes()
    payload = json.loads(explanation_path.read_text(encoding="utf-8"))
    payload["confidence"] = 0.123
    explanation_path.write_text(json.dumps(payload), encoding="utf-8")
    explanation_before = explanation_path.read_bytes()

    response = client.post(
        f"/explanations/{explanation_id}/validate",
        json={"diagnosis_id": diagnosis_id},
    )
    assert response.status_code == 422
    assert response.json()["overall_valid"] is False
    assert diagnosis_path.read_bytes() == diagnosis_before
    assert explanation_path.read_bytes() == explanation_before
    assert list(settings.explanation.output_dir.glob("*.validation.json"))

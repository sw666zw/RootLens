"""Health, correlation, metrics, and app-factory behavior."""

import re

from diagnosis_service.main import create_app


def test_health_is_exact_and_request_ids_are_generated_and_preserved(client):
    generated = client.get("/health")
    assert generated.status_code == 200
    assert generated.json() == {"status": "ok", "service": "diagnosis"}
    assert re.fullmatch(r"[0-9a-f-]{36}", generated.headers["X-Request-ID"])

    supplied = client.get("/health", headers={"X-Request-ID": "caller-id"})
    assert supplied.headers["X-Request-ID"] == "caller-id"


def test_metrics_normalize_routes_and_do_not_count_metrics(client):
    client.get("/incidents/baseline-20260805-abc")
    first = client.get("/metrics").text
    second = client.get("/metrics").text
    assert 'route="/incidents/{scenario_id}"' in first
    assert 'route="/metrics"' not in first
    assert first == second


def test_repeated_create_app_owns_distinct_registries(settings, fake_diagnosis):
    first = create_app(settings, diagnosis_service=fake_diagnosis)
    second = create_app(settings, diagnosis_service=fake_diagnosis)
    assert first.state.metrics.registry is not second.state.metrics.registry
    assert len(first.user_middleware) == len(second.user_middleware) == 2


def test_blank_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "   "})
    assert response.headers["X-Request-ID"].strip()

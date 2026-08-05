"""Real engine-library orchestration with isolated HTTPX transports."""

import json
from pathlib import Path

import httpx
import pytest
from rootlens_diagnosis.config import DiagnosisConfig

from diagnosis_service.services.diagnosis import (
    DiagnosisService,
    DiagnosisTelemetryUnavailable,
    TelemetryClients,
)

TRACE_ID = "a" * 32


def _incident(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "scenario_id": "ground-truth-name-must-not-reach-engine",
                "scenario_name": "inventory-unavailable",
                "expected_root_cause": "inventory_service_unavailable",
                "expected_symptoms": ["secret answer"],
                "target_service": "inventory",
                "started_at": "2026-08-05T12:00:00Z",
                "ended_at": "2026-08-05T12:00:01Z",
                "request_ids": ["request-1"],
                "trace_ids": [TRACE_ID],
                "total_requests": 1,
                "concurrency": 1,
            }
        ),
        encoding="utf-8",
    )


def _prometheus(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"status": "success", "data": {"resultType": "vector", "result": []}}
    )


def _loki(request: httpx.Request) -> httpx.Response:
    if request.url.host == "unavailable.test":
        return httpx.Response(503)
    return httpx.Response(
        200,
        json={"status": "success", "data": {"resultType": "streams", "result": []}},
    )


def _jaeger(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"result": {"resourceSpans": []}})


def _client(host: str, handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"http://{host}", transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_partial_diagnosis_is_written_when_allowed(tmp_path: Path):
    incident = tmp_path / "incident.json"
    output = tmp_path / "diagnoses"
    _incident(incident)
    clients = (
        _client("prometheus.test", _prometheus),
        _client("unavailable.test", _loki),
        _client("jaeger.test", _jaeger),
    )
    service = DiagnosisService(
        DiagnosisConfig(
            "http://prometheus.test",
            "http://unavailable.test",
            "http://jaeger.test",
            output,
            1,
            1,
        ),
        TelemetryClients(*clients),
    )
    try:
        report = await service.diagnose(
            incident, require_all_sources=False, window_padding_seconds=None
        )
    finally:
        for client in clients:
            await client.aclose()
    assert report.telemetry_coverage.logs == "unavailable"
    assert (output / f"{report.diagnosis_id}.json").is_file()
    serialized = (output / f"{report.diagnosis_id}.json").read_text()
    assert "expected_root_cause" not in serialized
    assert "expected_symptoms" not in serialized


@pytest.mark.asyncio
async def test_require_all_sources_returns_failure_after_writing(tmp_path: Path):
    incident = tmp_path / "incident.json"
    output = tmp_path / "diagnoses"
    _incident(incident)
    clients = (
        _client("prometheus.test", _prometheus),
        _client("unavailable.test", _loki),
        _client("jaeger.test", _jaeger),
    )
    service = DiagnosisService(
        DiagnosisConfig(
            "http://prometheus.test",
            "http://unavailable.test",
            "http://jaeger.test",
            output,
            1,
            1,
        ),
        TelemetryClients(*clients),
    )
    try:
        with pytest.raises(DiagnosisTelemetryUnavailable):
            await service.diagnose(
                incident, require_all_sources=True, window_padding_seconds=2
            )
    finally:
        for client in clients:
            await client.aclose()
    assert len(list(output.glob("diagnosis-*.json"))) == 1


@pytest.mark.asyncio
async def test_every_unavailable_source_returns_failure_after_writing(tmp_path: Path):
    incident = tmp_path / "incident.json"
    output = tmp_path / "diagnoses"
    _incident(incident)

    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    clients = (
        _client("prometheus.test", unavailable),
        _client("loki.test", unavailable),
        _client("jaeger.test", unavailable),
    )
    service = DiagnosisService(
        DiagnosisConfig(
            "http://prometheus.test",
            "http://loki.test",
            "http://jaeger.test",
            output,
            1,
            1,
        ),
        TelemetryClients(*clients),
    )
    try:
        with pytest.raises(DiagnosisTelemetryUnavailable) as raised:
            await service.diagnose(
                incident, require_all_sources=False, window_padding_seconds=None
            )
    finally:
        for client in clients:
            await client.aclose()
    assert raised.value.report.suspected_root_cause == "unknown"
    assert raised.value.report.confidence == 0
    assert len(list(output.glob("diagnosis-*.json"))) == 1

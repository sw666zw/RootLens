"""Scenario runner behavior using only HTTPX MockTransport."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from rootlens_scenarios.cli import build_parser, run_command
from rootlens_scenarios.client import ScenarioClient, valid_trace_id
from rootlens_scenarios.models import (
    IncidentReport,
    ScenarioName,
    ScenarioParameters,
)
from rootlens_scenarios.runner import (
    ScenarioRunner,
    ScenarioValidationError,
    write_report_atomic,
)

VALID_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


class MockServices:
    def __init__(self, order_status: int = 201) -> None:
        self.order_status = order_status
        self.events: list[str] = []
        self.request_ids: list[str] = []
        self.idempotency_keys: list[str] = []
        self.reset_calls = 0
        self.active = 0
        self.maximum_active = 0

    async def inventory(self, request: httpx.Request) -> httpx.Response:
        self.events.append(f"inventory:{request.method}:{request.url.path}")
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/items" and request.method == "POST":
            return httpx.Response(201, json={})
        if request.url.path == "/internal/faults/reservation":
            if request.method == "DELETE":
                self.reset_calls += 1
            return httpx.Response(200, json={"delay_ms": 0, "failure_mode": "none"})
        if request.method == "GET" and request.url.path.startswith("/items/"):
            return httpx.Response(200, json={"quantity": 3})
        return httpx.Response(404)

    async def order(self, request: httpx.Request) -> httpx.Response:
        self.events.append(f"order:{request.method}:{request.url.path}")
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        self.request_ids.append(request.headers["X-Request-ID"])
        self.idempotency_keys.append(request.headers["Idempotency-Key"])
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        return httpx.Response(
            self.order_status,
            headers={
                "X-Request-ID": request.headers["X-Request-ID"],
                "X-Trace-ID": VALID_TRACE_ID,
            },
        )


def scenario_client(services: MockServices) -> ScenarioClient:
    return ScenarioClient(
        httpx.AsyncClient(
            base_url="http://inventory.test",
            transport=httpx.MockTransport(services.inventory),
        ),
        httpx.AsyncClient(
            base_url="http://order.test",
            transport=httpx.MockTransport(services.order),
        ),
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "baseline", "--requests", "0"],
        ["run", "baseline", "--concurrency", "-1"],
        ["run", "inventory-latency", "--delay-ms", "10001"],
    ],
)
def test_command_line_rejects_invalid_positive_values(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(arguments)


def test_parameters_reject_concurrency_above_requests() -> None:
    with pytest.raises(ValueError, match="may not exceed"):
        ScenarioParameters(requests=2, concurrency=3).validate(ScenarioName.BASELINE)


@pytest.mark.asyncio
async def test_health_checks_happen_before_setup_and_traffic(tmp_path: Path) -> None:
    services = MockServices()
    client = scenario_client(services)

    await ScenarioRunner(client, tmp_path).run(
        ScenarioName.BASELINE, ScenarioParameters(requests=2, concurrency=1)
    )
    await client.aclose()

    assert services.events[:2] == [
        "inventory:GET:/health",
        "order:GET:/health",
    ]
    first_order = services.events.index("order:POST:/orders")
    assert services.events.index("inventory:POST:/items") < first_order


@pytest.mark.asyncio
async def test_unique_correlation_values_and_concurrency_limit(
    tmp_path: Path,
) -> None:
    services = MockServices()
    client = scenario_client(services)

    report, path = await ScenarioRunner(client, tmp_path).run(
        ScenarioName.BASELINE,
        ScenarioParameters(requests=8, concurrency=3),
    )
    await client.aclose()

    assert len(set(services.request_ids)) == 8
    assert len(set(services.idempotency_keys)) == 8
    assert services.maximum_active <= 3
    assert report.request_ids == services.request_ids
    assert not any(key in path.read_text() for key in services.idempotency_keys)


@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        (ScenarioName.BASELINE, 201),
        (ScenarioName.INVENTORY_LATENCY, 201),
        (ScenarioName.INVENTORY_UNAVAILABLE, 503),
    ],
)
@pytest.mark.asyncio
async def test_scenario_validates_expected_broad_result(
    tmp_path: Path,
    scenario: ScenarioName,
    status: int,
) -> None:
    services = MockServices(status)
    client = scenario_client(services)

    report, _ = await ScenarioRunner(client, tmp_path).run(
        scenario, ScenarioParameters(requests=3, concurrency=2, delay_ms=1)
    )
    await client.aclose()

    assert report.response_status_counts == {str(status): 3}
    assert services.reset_calls >= 1


@pytest.mark.asyncio
async def test_unexpected_result_writes_report_resets_and_raises(
    tmp_path: Path,
) -> None:
    services = MockServices(503)
    client = scenario_client(services)

    with pytest.raises(ScenarioValidationError):
        await ScenarioRunner(client, tmp_path).run(
            ScenarioName.BASELINE,
            ScenarioParameters(requests=2, concurrency=1),
        )
    await client.aclose()

    assert len(list(tmp_path.glob("*.json"))) == 1
    assert services.reset_calls >= 2


@pytest.mark.asyncio
async def test_request_failure_still_resets_fault(tmp_path: Path) -> None:
    services = MockServices()

    async def broken_order(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        raise httpx.ConnectError("offline", request=request)

    client = ScenarioClient(
        httpx.AsyncClient(
            base_url="http://inventory.test",
            transport=httpx.MockTransport(services.inventory),
        ),
        httpx.AsyncClient(
            base_url="http://order.test",
            transport=httpx.MockTransport(broken_order),
        ),
    )

    with pytest.raises(ScenarioValidationError):
        await ScenarioRunner(client, tmp_path).run(
            ScenarioName.BASELINE, ScenarioParameters(requests=1, concurrency=1)
        )
    await client.aclose()

    assert services.reset_calls >= 2


@pytest.mark.asyncio
async def test_report_failure_still_resets_fault(
    tmp_path: Path, monkeypatch: Any
) -> None:
    services = MockServices()
    client = scenario_client(services)

    def fail_report(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("rootlens_scenarios.runner.write_report_atomic", fail_report)
    with pytest.raises(OSError, match="disk full"):
        await ScenarioRunner(client, tmp_path).run(
            ScenarioName.BASELINE, ScenarioParameters(requests=1, concurrency=1)
        )
    await client.aclose()

    assert services.reset_calls >= 2


@pytest.mark.asyncio
async def test_report_fields_timestamps_and_trace_filtering(tmp_path: Path) -> None:
    services = MockServices()
    original_order = services.order
    calls = 0

    async def mixed_traces(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        response = await original_order(request)
        if request.url.path == "/health":
            return response
        calls += 1
        response.headers["X-Trace-ID"] = [
            VALID_TRACE_ID,
            "0" * 32,
            "not-a-trace",
        ][calls - 1]
        return response

    client = ScenarioClient(
        httpx.AsyncClient(
            base_url="http://inventory.test",
            transport=httpx.MockTransport(services.inventory),
        ),
        httpx.AsyncClient(
            base_url="http://order.test",
            transport=httpx.MockTransport(mixed_traces),
        ),
    )
    report, path = await ScenarioRunner(client, tmp_path).run(
        ScenarioName.BASELINE, ScenarioParameters(requests=3, concurrency=1)
    )
    await client.aclose()

    required = {
        "schema_version",
        "scenario_id",
        "scenario_name",
        "started_at",
        "ended_at",
        "target_service",
        "parameters",
        "expected_root_cause",
        "expected_symptoms",
        "inventory_sku",
        "total_requests",
        "concurrency",
        "response_status_counts",
        "successful_requests",
        "failed_requests",
        "minimum_duration_ms",
        "maximum_duration_ms",
        "average_duration_ms",
        "request_ids",
        "trace_ids",
    }
    payload = json.loads(path.read_text())
    assert set(payload) == required
    assert datetime.fromisoformat(report.started_at.replace("Z", "+00:00")).tzinfo
    assert datetime.fromisoformat(report.ended_at.replace("Z", "+00:00")).tzinfo
    assert report.trace_ids == [VALID_TRACE_ID]


def sample_report() -> IncidentReport:
    return IncidentReport(
        schema_version="1.0",
        scenario_id="baseline-safe-id",
        scenario_name="baseline",
        started_at="2026-08-03T12:00:00.000Z",
        ended_at="2026-08-03T12:00:01.000Z",
        target_service="inventory",
        parameters={"requests": 1, "concurrency": 1},
        expected_root_cause="none",
        expected_symptoms=["orders succeed"],
        inventory_sku="SCN-1",
        total_requests=1,
        concurrency=1,
        response_status_counts={"201": 1},
        successful_requests=1,
        failed_requests=0,
        minimum_duration_ms=1.0,
        maximum_duration_ms=1.0,
        average_duration_ms=1.0,
        request_ids=["request-1"],
        trace_ids=[],
    )


def test_report_write_uses_atomic_replace(tmp_path: Path, monkeypatch: Any) -> None:
    replacements: list[tuple[Path, Path]] = []
    original = Path.replace

    def recording_replace(source: Path, target: Path) -> Path:
        replacements.append((source, target))
        return original(source, target)

    monkeypatch.setattr(Path, "replace", recording_replace)
    destination = write_report_atomic(sample_report(), tmp_path)

    assert destination.is_file()
    assert len(replacements) == 1
    assert replacements[0][0].suffix == ".tmp"
    assert list(tmp_path.glob("*.tmp")) == []
    assert destination.read_text().endswith("\n")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (VALID_TRACE_ID.upper(), VALID_TRACE_ID),
        ("0" * 32, None),
        ("short", None),
        (None, None),
    ],
)
def test_only_valid_returned_trace_ids_are_accepted(
    value: str | None, expected: str | None
) -> None:
    assert valid_trace_id(value) == expected


@pytest.mark.asyncio
async def test_failed_validation_returns_nonzero(monkeypatch: Any) -> None:
    async def fail_run(*args: object, **kwargs: object) -> None:
        raise ScenarioValidationError("unexpected status")

    monkeypatch.setattr(ScenarioRunner, "run", fail_run)
    args = SimpleNamespace(
        command="run",
        scenario="baseline",
        requests=1,
        concurrency=1,
        output_dir=Path("unused"),
    )

    assert await run_command(args) == 1

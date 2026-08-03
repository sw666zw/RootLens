"""Scenario orchestration and deterministic ground-truth report writing."""

import asyncio
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from uuid import uuid4

from rootlens_scenarios.client import ScenarioClient
from rootlens_scenarios.models import (
    IncidentReport,
    RequestObservation,
    ScenarioName,
    ScenarioParameters,
)

ROOT_CAUSES = {
    ScenarioName.BASELINE: "none",
    ScenarioName.INVENTORY_LATENCY: "inventory_reservation_latency",
    ScenarioName.INVENTORY_UNAVAILABLE: "inventory_service_unavailable",
}
EXPECTED_STATUS = {
    ScenarioName.BASELINE: 201,
    ScenarioName.INVENTORY_LATENCY: 201,
    ScenarioName.INVENTORY_UNAVAILABLE: 503,
}
EXPECTED_SYMPTOMS = {
    ScenarioName.BASELINE: ["orders succeed"],
    ScenarioName.INVENTORY_LATENCY: ["orders succeed", "order latency increases"],
    ScenarioName.INVENTORY_UNAVAILABLE: [
        "orders return HTTP 503",
        "inventory quantity remains unchanged",
    ],
}


class ScenarioValidationError(RuntimeError):
    """Raised after reporting when broad scenario outcomes do not match."""


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_scenario_id(scenario: ScenarioName) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{scenario.value}-{timestamp}-{uuid4().hex[:8]}"


def write_report_atomic(report: IncidentReport, output_dir: Path) -> Path:
    """Write one report using a same-directory temporary file and rename."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{report.scenario_id}.json"
    temporary = output_dir / f".{report.scenario_id}.{uuid4().hex}.tmp"
    payload = (
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    try:
        with temporary.open("x", encoding="utf-8") as report_file:
            report_file.write(payload)
            report_file.flush()
            os.fsync(report_file.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


class ScenarioRunner:
    def __init__(self, client: ScenarioClient, output_dir: Path) -> None:
        self._client = client
        self._output_dir = output_dir

    async def reset(self) -> None:
        await self._client.check_health()
        await self._client.reset_fault()

    async def run(
        self,
        scenario: ScenarioName,
        parameters: ScenarioParameters,
    ) -> tuple[IncidentReport, Path]:
        parameters.validate(scenario)
        scenario_id = make_scenario_id(scenario)
        sku = f"SCN-{uuid4().hex[:24]}"
        started_at = utc_timestamp()
        observations: list[RequestObservation] = []
        initial_quantity: int | None = None
        final_quantity: int | None = None
        try:
            await self._client.check_health()
            await self._client.create_inventory_item(sku, parameters.requests)
            initial_quantity = parameters.requests
            await self._configure(scenario, parameters)
            observations = await self._send_traffic(
                sku, parameters.requests, parameters.concurrency
            )
            if scenario is ScenarioName.INVENTORY_UNAVAILABLE:
                final_quantity = await self._client.inventory_quantity(sku)
            report = self._build_report(
                scenario,
                scenario_id,
                sku,
                started_at,
                parameters,
                observations,
            )
            report_path = write_report_atomic(report, self._output_dir)
            try:
                self._validate(
                    scenario,
                    observations,
                    initial_quantity=initial_quantity,
                    final_quantity=final_quantity,
                )
            except ScenarioValidationError as error:
                raise ScenarioValidationError(
                    f"{error}; report written to {report_path}"
                ) from error
            return report, report_path
        finally:
            await self._client.reset_fault()

    async def _configure(
        self,
        scenario: ScenarioName,
        parameters: ScenarioParameters,
    ) -> None:
        if scenario is ScenarioName.INVENTORY_LATENCY:
            await self._client.configure_fault(parameters.delay_ms, "none")
        elif scenario is ScenarioName.INVENTORY_UNAVAILABLE:
            await self._client.configure_fault(0, "service_unavailable")
        else:
            await self._client.reset_fault()

    async def _send_traffic(
        self,
        sku: str,
        requests: int,
        concurrency: int,
    ) -> list[RequestObservation]:
        semaphore = asyncio.Semaphore(concurrency)

        async def send_one() -> RequestObservation:
            async with semaphore:
                return await self._client.create_order(
                    sku,
                    f"scenario-request-{uuid4()}",
                    f"scenario-order-{uuid4()}",
                )

        return list(await asyncio.gather(*(send_one() for _ in range(requests))))

    def _build_report(
        self,
        scenario: ScenarioName,
        scenario_id: str,
        sku: str,
        started_at: str,
        parameters: ScenarioParameters,
        observations: list[RequestObservation],
    ) -> IncidentReport:
        durations = [item.duration_ms for item in observations]
        statuses = Counter(
            str(item.status_code) if item.status_code is not None else "network_error"
            for item in observations
        )
        successful = sum(
            item.status_code is not None and 200 <= item.status_code < 300
            for item in observations
        )
        traces = sorted(
            {item.trace_id for item in observations if item.trace_id is not None}
        )
        scenario_parameters: dict[str, int] = {
            "requests": parameters.requests,
            "concurrency": parameters.concurrency,
        }
        if scenario is ScenarioName.INVENTORY_LATENCY:
            scenario_parameters["delay_ms"] = parameters.delay_ms
        return IncidentReport(
            schema_version="1.0",
            scenario_id=scenario_id,
            scenario_name=scenario.value,
            started_at=started_at,
            ended_at=utc_timestamp(),
            target_service="inventory",
            parameters=scenario_parameters,
            expected_root_cause=ROOT_CAUSES[scenario],
            expected_symptoms=EXPECTED_SYMPTOMS[scenario],
            inventory_sku=sku,
            total_requests=len(observations),
            concurrency=parameters.concurrency,
            response_status_counts=dict(sorted(statuses.items())),
            successful_requests=successful,
            failed_requests=len(observations) - successful,
            minimum_duration_ms=round(min(durations), 3),
            maximum_duration_ms=round(max(durations), 3),
            average_duration_ms=round(fmean(durations), 3),
            request_ids=[item.request_id for item in observations],
            trace_ids=traces,
        )

    def _validate(
        self,
        scenario: ScenarioName,
        observations: list[RequestObservation],
        *,
        initial_quantity: int | None,
        final_quantity: int | None,
    ) -> None:
        expected = EXPECTED_STATUS[scenario]
        if not observations or any(
            item.status_code != expected for item in observations
        ):
            actual = Counter(item.status_code for item in observations)
            raise ScenarioValidationError(
                f"expected every response to be HTTP {expected}; got {dict(actual)}"
            )
        if (
            scenario is ScenarioName.INVENTORY_UNAVAILABLE
            and final_quantity is not None
            and final_quantity != initial_quantity
        ):
            raise ScenarioValidationError(
                "inventory quantity changed during the unavailable scenario"
            )

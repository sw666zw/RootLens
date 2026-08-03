"""Typed scenario inputs, observations, and ground-truth reports."""

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ScenarioName(StrEnum):
    BASELINE = "baseline"
    INVENTORY_LATENCY = "inventory-latency"
    INVENTORY_UNAVAILABLE = "inventory-unavailable"


@dataclass(frozen=True)
class ScenarioParameters:
    requests: int = 20
    concurrency: int = 5
    delay_ms: int = 1500

    def validate(self, scenario: ScenarioName) -> None:
        if self.requests <= 0:
            raise ValueError("requests must be a positive integer")
        if self.concurrency <= 0:
            raise ValueError("concurrency must be a positive integer")
        if self.concurrency > self.requests:
            raise ValueError("concurrency may not exceed requests")
        if scenario is ScenarioName.INVENTORY_LATENCY and not (
            1 <= self.delay_ms <= 10_000
        ):
            raise ValueError("delay-ms must be between 1 and 10000")


@dataclass(frozen=True)
class RequestObservation:
    status_code: int | None
    duration_ms: float
    request_id: str
    trace_id: str | None


@dataclass(frozen=True)
class IncidentReport:
    schema_version: str
    scenario_id: str
    scenario_name: str
    started_at: str
    ended_at: str
    target_service: str
    parameters: dict[str, Any]
    expected_root_cause: str
    expected_symptoms: list[str]
    inventory_sku: str
    total_requests: int
    concurrency: int
    response_status_counts: dict[str, int]
    successful_requests: int
    failed_requests: int
    minimum_duration_ms: float
    maximum_duration_ms: float
    average_duration_ms: float
    request_ids: list[str]
    trace_ids: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

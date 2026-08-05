"""Incident API projections that deliberately omit ground truth."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IncidentSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scenario_id: str
    scenario_name: str
    started_at: datetime
    ended_at: datetime
    total_requests: int
    successful_requests: int
    failed_requests: int


class IncidentDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scenario_id: str
    started_at: datetime
    ended_at: datetime
    total_requests: int
    concurrency: int
    response_status_counts: dict[str, int]
    successful_requests: int
    failed_requests: int
    request_id_count: int
    trace_id_count: int
    inventory_sku: str | None = None

    @classmethod
    def from_report(cls, report: dict[str, object]) -> "IncidentDetail":
        return cls.model_validate(
            {
                **report,
                "request_id_count": len(report.get("request_ids", [])),
                "trace_id_count": len(report.get("trace_ids", [])),
            }
        )

"""Ground-truth-safe incident listing and detail endpoints."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError

from diagnosis_service.repositories.report_files import (
    InvalidReportError,
    ReportNotFoundError,
    UnsupportedReportError,
)
from diagnosis_service.schemas.incidents import IncidentDetail, IncidentSummary

router = APIRouter(prefix="/incidents", tags=["incidents"])
Scenario = Literal["baseline", "inventory-latency", "inventory-unavailable"]


@router.get("")
def list_incidents(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    scenario_name: Scenario | None = None,
) -> list[IncidentSummary]:
    reports = request.app.state.repositories.incidents.list(limit=200)
    try:
        summaries = [IncidentSummary.model_validate(report) for report in reports]
    except ValidationError as error:
        raise HTTPException(422, "The stored report is invalid.") from error
    if scenario_name is not None:
        summaries = [item for item in summaries if item.scenario_name == scenario_name]
    return summaries[:limit]


@router.get("/{scenario_id}")
def get_incident(scenario_id: str, request: Request) -> IncidentDetail:
    try:
        report = request.app.state.repositories.incidents.get(scenario_id)
        return IncidentDetail.from_report(report)
    except (ReportNotFoundError, UnsupportedReportError):
        raise HTTPException(404, "Incident report not found.") from None
    except (InvalidReportError, ValidationError, TypeError):
        raise HTTPException(422, "The stored report is invalid.") from None

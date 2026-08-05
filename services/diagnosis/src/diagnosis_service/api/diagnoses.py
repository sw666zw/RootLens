"""Deterministic diagnosis endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError
from rootlens_diagnosis.models import DiagnosisReport, RootCause, SourceStatus

from diagnosis_service.logging_config import LOGGER_NAME
from diagnosis_service.repositories.report_files import (
    InvalidReportError,
    ReportNotFoundError,
    UnsupportedReportError,
)
from diagnosis_service.schemas.diagnoses import (
    DiagnoseRequest,
    DiagnosisResponse,
    DiagnosisSummary,
)
from diagnosis_service.services.diagnosis import DiagnosisTelemetryUnavailable
from diagnosis_service.tracing import set_span_attributes

router = APIRouter(tags=["diagnoses"])
logger = logging.getLogger(f"{LOGGER_NAME}.domain")


@router.post(
    "/incidents/{scenario_id}/diagnose",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_201_CREATED,
)
async def diagnose(
    scenario_id: str, payload: DiagnoseRequest, request: Request
) -> DiagnosisResponse:
    repositories = request.app.state.repositories
    try:
        incident_path = repositories.incidents.path_for(scenario_id)
    except (ReportNotFoundError, UnsupportedReportError):
        raise HTTPException(404, "Incident report not found.") from None
    except InvalidReportError:
        raise HTTPException(422, "The stored report is invalid.") from None
    logger.info(
        "diagnosis_started",
        extra={
            "incident_id": scenario_id,
            "require_all_sources": payload.require_all_sources,
        },
    )
    set_span_attributes({"rootlens.incident.id": scenario_id})
    try:
        report = await request.app.state.diagnosis_service.diagnose(
            incident_path,
            require_all_sources=payload.require_all_sources,
            window_padding_seconds=payload.window_padding_seconds,
        )
    except DiagnosisTelemetryUnavailable as error:
        request.app.state.metrics.diagnosis_runs.labels(
            "failed", error.report.suspected_root_cause.value
        ).inc()
        logger.error(
            "diagnosis_failed",
            extra={"incident_id": scenario_id, "reason": "telemetry_unavailable"},
        )
        raise HTTPException(
            503, "Telemetry required for diagnosis is unavailable."
        ) from None
    except (OSError, ValueError):
        request.app.state.metrics.diagnosis_runs.labels("failed", "unknown").inc()
        logger.error(
            "diagnosis_failed",
            extra={"incident_id": scenario_id, "reason": "invalid_incident"},
        )
        raise HTTPException(422, "The stored report is invalid.") from None
    partial = any(
        value is not SourceStatus.AVAILABLE
        for value in report.telemetry_coverage.model_dump().values()
    )
    outcome = "partial" if partial else "completed"
    request.app.state.metrics.diagnosis_runs.labels(
        outcome, report.suspected_root_cause.value
    ).inc()
    set_span_attributes(
        {
            "rootlens.diagnosis.id": report.diagnosis_id,
            "rootlens.diagnosis.root_cause": report.suspected_root_cause.value,
        }
    )
    logger.log(
        logging.WARNING if partial else logging.INFO,
        "diagnosis_completed",
        extra={
            "incident_id": scenario_id,
            "diagnosis_id": report.diagnosis_id,
            "suspected_root_cause": report.suspected_root_cause.value,
            "affected_service": report.affected_service,
            "confidence": report.confidence,
            "telemetry_source_count": (
                report.telemetry_coverage.available_source_count()
            ),
            "partial_telemetry": partial,
        },
    )
    return DiagnosisResponse(
        **report.model_dump(mode="json"),
        report_url=f"/diagnoses/{report.diagnosis_id}",
    )


@router.get("/diagnoses", response_model=list[DiagnosisSummary])
def list_diagnoses(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    root_cause: RootCause | None = None,
    confidence_level: str | None = None,
) -> list[DiagnosisSummary]:
    reports = request.app.state.repositories.diagnoses.list(200)
    try:
        summaries = [DiagnosisSummary.model_validate(report) for report in reports]
    except ValidationError:
        raise HTTPException(422, "The stored report is invalid.") from None
    if root_cause is not None:
        summaries = [x for x in summaries if x.suspected_root_cause == root_cause]
    if confidence_level is not None:
        summaries = [x for x in summaries if x.confidence_level == confidence_level]
    return summaries[:limit]


@router.get("/diagnoses/{diagnosis_id}")
def get_diagnosis(diagnosis_id: str, request: Request) -> dict[str, object]:
    try:
        raw = request.app.state.repositories.diagnoses.get(diagnosis_id)
        return DiagnosisReport.model_validate(raw).model_dump(mode="json")
    except (ReportNotFoundError, UnsupportedReportError):
        raise HTTPException(404, "Diagnosis report not found.") from None
    except (InvalidReportError, ValidationError):
        raise HTTPException(422, "The stored report is invalid.") from None

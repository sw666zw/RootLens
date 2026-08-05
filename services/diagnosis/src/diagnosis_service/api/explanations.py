"""Safe explanation generation, retrieval, and offline validation."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from rootlens_diagnosis.explanation_models import ExplanationReport
from rootlens_diagnosis.explanation_providers import ExplanationProviderError

from diagnosis_service.logging_config import LOGGER_NAME
from diagnosis_service.repositories.report_files import (
    InvalidReportError,
    ReportNotFoundError,
    UnsupportedReportError,
)
from diagnosis_service.schemas.explanations import (
    ExplainRequest,
    ExplanationResponse,
    ExplanationSummary,
    ValidateExplanationRequest,
    ValidationResponse,
)
from diagnosis_service.services.explanations import OpenAIDisabledError
from diagnosis_service.tracing import set_span_attributes

router = APIRouter(tags=["explanations"])
logger = logging.getLogger(f"{LOGGER_NAME}.domain")


@router.post(
    "/diagnoses/{diagnosis_id}/explain",
    response_model=ExplanationResponse,
    status_code=status.HTTP_201_CREATED,
)
def explain(
    diagnosis_id: str, payload: ExplainRequest, request: Request
) -> ExplanationResponse:
    provider = payload.provider or request.app.state.settings.explanation.provider
    metric_provider = provider if provider in {"template", "openai"} else "template"
    if provider not in {"template", "openai"}:
        request.app.state.metrics.explanation_runs.labels(
            metric_provider, "invalid"
        ).inc()
        raise HTTPException(400, "Unsupported explanation provider.")
    try:
        diagnosis_path = request.app.state.repositories.diagnoses.path_for(diagnosis_id)
    except (ReportNotFoundError, UnsupportedReportError):
        raise HTTPException(404, "Diagnosis report not found.") from None
    except InvalidReportError:
        raise HTTPException(422, "The stored report is invalid.") from None
    set_span_attributes(
        {
            "rootlens.diagnosis.id": diagnosis_id,
            "rootlens.explanation.provider": provider,
        }
    )
    try:
        report = request.app.state.explanation_service.explain(
            diagnosis_path,
            provider_name=provider,
            allow_template_fallback=payload.allow_template_fallback,
        )
    except OpenAIDisabledError:
        request.app.state.metrics.explanation_runs.labels("openai", "failed").inc()
        logger.error(
            "explanation_failed",
            extra={
                "diagnosis_id": diagnosis_id,
                "provider": "openai",
                "reason": "provider_disabled",
            },
        )
        raise HTTPException(503, "OpenAI explanations are not enabled.") from None
    except ExplanationProviderError:
        request.app.state.metrics.explanation_runs.labels(provider, "failed").inc()
        logger.error(
            "explanation_failed",
            extra={
                "diagnosis_id": diagnosis_id,
                "provider": provider,
                "reason": "provider_unavailable",
            },
        )
        raise HTTPException(503, "Explanation provider unavailable.") from None
    except (OSError, ValueError):
        request.app.state.metrics.explanation_runs.labels(provider, "invalid").inc()
        logger.error(
            "explanation_failed",
            extra={
                "diagnosis_id": diagnosis_id,
                "provider": provider,
                "reason": "invalid_report",
            },
        )
        raise HTTPException(422, "The stored report is invalid.") from None
    metric_status = report.provider_status.value
    request.app.state.metrics.explanation_runs.labels(
        report.provider, metric_status
    ).inc()
    set_span_attributes(
        {
            "rootlens.explanation.status": report.provider_status.value,
            "rootlens.explanation.id": report.explanation_id,
        }
    )
    logger.info(
        "explanation_completed",
        extra={
            "diagnosis_id": diagnosis_id,
            "explanation_id": report.explanation_id,
            "provider": report.provider,
            "provider_status": report.provider_status.value,
        },
    )
    return ExplanationResponse(
        **report.model_dump(mode="json"),
        report_url=f"/explanations/{report.explanation_id}",
    )


@router.get("/explanations", response_model=list[ExplanationSummary])
def list_explanations(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    provider: str | None = None,
    provider_status: str | None = None,
) -> list[ExplanationSummary]:
    reports = request.app.state.repositories.explanations.list(200)
    try:
        summaries = [ExplanationSummary.model_validate(item) for item in reports]
    except ValidationError:
        raise HTTPException(422, "The stored report is invalid.") from None
    if provider is not None:
        summaries = [item for item in summaries if item.provider == provider]
    if provider_status is not None:
        summaries = [
            item for item in summaries if item.provider_status.value == provider_status
        ]
    return summaries[:limit]


@router.get("/explanations/{explanation_id}")
def get_explanation(explanation_id: str, request: Request) -> dict[str, object]:
    try:
        raw = request.app.state.repositories.explanations.get(explanation_id)
        return ExplanationReport.model_validate(raw).model_dump(mode="json")
    except (ReportNotFoundError, UnsupportedReportError):
        raise HTTPException(404, "Explanation report not found.") from None
    except (InvalidReportError, ValidationError):
        raise HTTPException(422, "The stored report is invalid.") from None


@router.post(
    "/explanations/{explanation_id}/validate", response_model=ValidationResponse
)
def validate_explanation(
    explanation_id: str,
    payload: ValidateExplanationRequest,
    request: Request,
    response: Response,
) -> ValidationResponse:
    try:
        explanation_path = request.app.state.repositories.explanations.path_for(
            explanation_id
        )
    except (ReportNotFoundError, UnsupportedReportError):
        raise HTTPException(404, "Explanation report not found.") from None
    except InvalidReportError:
        raise HTTPException(422, "The stored report is invalid.") from None
    try:
        diagnosis_path = request.app.state.repositories.diagnoses.path_for(
            payload.diagnosis_id
        )
    except (ReportNotFoundError, UnsupportedReportError):
        raise HTTPException(404, "Diagnosis report not found.") from None
    except InvalidReportError:
        raise HTTPException(422, "The stored report is invalid.") from None
    try:
        report = request.app.state.explanation_service.validate(
            explanation_path, diagnosis_path
        )
    except (OSError, ValueError):
        raise HTTPException(422, "The stored report is invalid.") from None
    if not report.overall_valid:
        response.status_code = 422
    return ValidationResponse(
        **report.model_dump(mode="json"),
        validation_report_id=report.validation_id,
    )

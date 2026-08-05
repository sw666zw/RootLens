"""Diagnosis request and response schemas."""

from pydantic import BaseModel, Field
from rootlens_diagnosis.models import RootCause, TelemetryCoverage


class DiagnoseRequest(BaseModel):
    require_all_sources: bool = False
    window_padding_seconds: int | None = Field(default=None, ge=0)


class DiagnosisResponse(BaseModel):
    diagnosis_id: str
    generated_at: str
    suspected_root_cause: RootCause
    affected_service: str | None
    confidence: float
    confidence_level: str
    summary: str
    telemetry_coverage: TelemetryCoverage
    warnings: list[str]
    report_url: str


class DiagnosisSummary(BaseModel):
    diagnosis_id: str
    generated_at: str
    suspected_root_cause: RootCause
    affected_service: str | None
    confidence: float
    confidence_level: str
    telemetry_coverage: TelemetryCoverage
    warnings: list[str]

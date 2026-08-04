"""Strict safe projection from a scenario report into analysis context."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_QUERY_WINDOW_SECONDS = 3600
MAX_CORRELATION_IDS = 500


def _utc_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("must include a timezone")
    return parsed.astimezone(UTC)


class IncidentAnalysisContext(BaseModel):
    """Only incident fields authorized for telemetry correlation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    started_at: datetime
    ended_at: datetime
    request_ids: tuple[str, ...] = Field(max_length=MAX_CORRELATION_IDS)
    trace_ids: tuple[str, ...] = Field(max_length=MAX_CORRELATION_IDS)
    total_requests: int = Field(ge=0)
    inventory_sku: str | None = Field(default=None, max_length=64)
    concurrency: int | None = Field(default=None, ge=1)

    @field_validator("started_at", "ended_at", mode="before")
    @classmethod
    def validate_timestamp(cls, value: Any) -> datetime:
        return _utc_datetime(value)

    @field_validator("request_ids")
    @classmethod
    def clean_request_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value for value in values if value.strip()))

    @field_validator("trace_ids")
    @classmethod
    def clean_trace_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value.lower() for value in values if value.strip()))


class AnalysisWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @property
    def seconds(self) -> int:
        return max(1, int((self.end - self.start).total_seconds()))


SAFE_FIELDS = {
    "started_at",
    "ended_at",
    "request_ids",
    "trace_ids",
    "total_requests",
    "inventory_sku",
    "concurrency",
}


def load_analysis_context(path: Path) -> IncidentAnalysisContext:
    """Load JSON and project it before constructing the analysis model."""
    if not path.is_file():
        raise ValueError("incident report path must be an existing file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("incident report must be readable valid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("incident report must contain a JSON object")
    projected = {key: raw[key] for key in SAFE_FIELDS if key in raw}
    try:
        context = IncidentAnalysisContext.model_validate(projected)
    except ValidationError as error:
        raise ValueError("incident report has invalid analysis context") from error
    if context.ended_at < context.started_at:
        raise ValueError("incident ended_at must not precede started_at")
    return context


def normalized_window(
    context: IncidentAnalysisContext, padding_seconds: int
) -> AnalysisWindow:
    """Create the single bounded UTC query window used by every source."""
    window = AnalysisWindow(
        start=context.started_at - timedelta(seconds=padding_seconds),
        end=context.ended_at + timedelta(seconds=padding_seconds),
    )
    if (window.end - window.start).total_seconds() > MAX_QUERY_WINDOW_SECONDS:
        raise ValueError(
            "incident telemetry window must not exceed "
            f"{MAX_QUERY_WINDOW_SECONDS} seconds"
        )
    return window

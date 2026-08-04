"""Focused adapter for Jaeger's stable v3 OTLP-based trace response."""

import asyncio
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from rootlens_diagnosis.incident_context import AnalysisWindow
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.telemetry.models import SourceResult, TraceData, TraceSpan

TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_TRACES = 100
MAX_SPANS_PER_TRACE = 2000
SAFE_ATTRIBUTE_PREFIXES = (
    "rootlens.",
    "http.",
    "db.system",
    "server.address",
    "network.protocol",
)


class JaegerResponseError(ValueError):
    """Raised for malformed v3 result envelopes."""


def valid_trace_id(value: str) -> bool:
    return bool(TRACE_ID_PATTERN.fullmatch(value)) and value != "0" * 32


class JaegerClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def collect(
        self, trace_ids: tuple[str, ...], window: AnalysisWindow
    ) -> SourceResult[tuple[TraceData, ...]]:
        valid_ids = tuple(value for value in trace_ids if valid_trace_id(value))[
            :MAX_TRACES
        ]
        if not valid_ids:
            return SourceResult(
                SourceStatus.PARTIAL,
                (),
                ("No valid trace IDs were available for Jaeger correlation",),
            )
        results = await asyncio.gather(
            *(self._get_trace(trace_id, window) for trace_id in valid_ids),
            return_exceptions=True,
        )
        traces: list[TraceData] = []
        failures = 0
        missing = 0
        for trace_id, result in zip(valid_ids, results, strict=True):
            if isinstance(result, BaseException):
                failures += 1
            elif result is None:
                missing += 1
            else:
                traces.append(TraceData(trace_id, result))
        if failures == len(valid_ids):
            return SourceResult(
                SourceStatus.UNAVAILABLE,
                (),
                ("Jaeger telemetry is unavailable",),
            )
        warnings: list[str] = []
        if failures:
            warnings.append(f"Failed to retrieve {failures} Jaeger traces")
        if missing:
            warnings.append(f"{missing} Jaeger traces were missing or expired")
        status = SourceStatus.PARTIAL if failures or missing else SourceStatus.AVAILABLE
        return SourceResult(status, tuple(traces), tuple(warnings))

    async def _get_trace(
        self, trace_id: str, window: AnalysisWindow
    ) -> tuple[TraceSpan, ...] | None:
        response = await self._client.get(
            f"/api/v3/traces/{trace_id}",
            params={
                "start_time": window.start.isoformat().replace("+00:00", "Z"),
                "end_time": window.end.isoformat().replace("+00:00", "Z"),
            },
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return parse_jaeger_v3_response(response.json(), trace_id)


def parse_jaeger_v3_response(
    payload: Any, expected_trace_id: str
) -> tuple[TraceSpan, ...]:
    """Unwrap one v3 result and retain only safe normalized span fields."""
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("result"), Mapping
    ):
        raise JaegerResponseError("Jaeger response has no result envelope")
    resource_spans = payload["result"].get("resourceSpans")
    if resource_spans is None:
        return ()
    if not isinstance(resource_spans, list):
        raise JaegerResponseError("Jaeger resourceSpans is malformed")
    spans: list[TraceSpan] = []
    for resource_group in resource_spans:
        if not isinstance(resource_group, Mapping):
            raise JaegerResponseError("Jaeger resource span is malformed")
        resource = resource_group.get("resource", {})
        resource_attributes = _attributes(
            resource.get("attributes", []) if isinstance(resource, Mapping) else []
        )
        service = str(resource_attributes.get("service.name", "unknown"))
        scope_spans = resource_group.get("scopeSpans", [])
        if not isinstance(scope_spans, list):
            raise JaegerResponseError("Jaeger scopeSpans is malformed")
        for scope_group in scope_spans:
            raw_spans = (
                scope_group.get("spans", []) if isinstance(scope_group, Mapping) else []
            )
            if not isinstance(raw_spans, list):
                raise JaegerResponseError("Jaeger spans is malformed")
            for raw_span in raw_spans:
                spans.append(_span(raw_span, service, expected_trace_id))
                if len(spans) > MAX_SPANS_PER_TRACE:
                    raise JaegerResponseError("Jaeger trace contains too many spans")
    return tuple(spans)


def _span(raw: Any, service: str, expected_trace_id: str) -> TraceSpan:
    if not isinstance(raw, Mapping):
        raise JaegerResponseError("Jaeger span is malformed")
    trace_id = str(raw.get("traceId", "")).lower()
    if trace_id != expected_trace_id:
        raise JaegerResponseError("Jaeger returned an unexpected trace ID")
    try:
        start_ns = int(raw["startTimeUnixNano"])
        end_ns = int(raw["endTimeUnixNano"])
    except (KeyError, TypeError, ValueError) as error:
        raise JaegerResponseError("Jaeger span timestamps are malformed") from error
    attributes = {
        key: value
        for key, value in _attributes(raw.get("attributes", [])).items()
        if key.startswith(SAFE_ATTRIBUTE_PREFIXES)
    }
    status = raw.get("status", {})
    status_code = status.get("code") if isinstance(status, Mapping) else None
    http_status = attributes.get(
        "http.response.status_code", attributes.get("http.status_code")
    )
    try:
        http_error = int(http_status) >= 500 if http_status is not None else False
    except (TypeError, ValueError):
        http_error = False
    error = status_code in {2, "STATUS_CODE_ERROR", "ERROR"} or http_error
    return TraceSpan(
        trace_id=trace_id,
        span_id=str(raw.get("spanId", "")),
        parent_span_id=str(raw["parentSpanId"]) if raw.get("parentSpanId") else None,
        service=service,
        name=_safe_span_name(str(raw.get("name", "unknown")), attributes),
        kind=str(raw.get("kind", "SPAN_KIND_UNSPECIFIED")),
        start_time=datetime.fromtimestamp(start_ns / 1_000_000_000, UTC),
        duration_ms=max(0.0, (end_ns - start_ns) / 1_000_000),
        error=error,
        attributes=attributes,
    )


def _attributes(raw_attributes: Any) -> dict[str, str | int | float | bool]:
    if not isinstance(raw_attributes, list):
        return {}
    attributes: dict[str, str | int | float | bool] = {}
    for item in raw_attributes:
        if not isinstance(item, Mapping) or not isinstance(item.get("key"), str):
            continue
        value = item.get("value")
        if not isinstance(value, Mapping):
            continue
        for value_key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            scalar = value.get(value_key)
            if isinstance(scalar, (str, int, float, bool)):
                attributes[item["key"]] = scalar
                break
    return attributes


def _safe_span_name(name: str, attributes: dict[str, str | int | float | bool]) -> str:
    """Retain bounded operation names while normalizing database statements."""
    if "db.system" in attributes or "db.system.name" in attributes:
        return "database operation"
    normalized = " ".join(name.split())
    return normalized[:120] if normalized else "unknown"

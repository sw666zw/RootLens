"""Loki range-query adapter and defensive structured-log parser."""

import json
from collections.abc import Mapping
from typing import Any

import httpx

from rootlens_diagnosis.incident_context import AnalysisWindow, IncidentAnalysisContext
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.telemetry.models import LogEntry, SourceResult

LOKI_QUERY = '{service=~"order|inventory"}'
MAX_LOG_ENTRIES = 5000
KNOWN_CATEGORIES = {
    "request_completed",
    "order_creation_succeeded",
    "order_creation_rejected",
    "order_creation_failed",
    "order_status_changed",
    "inventory_reservation_succeeded",
    "inventory_reservation_rejected",
    "inventory_reservation_failed",
}
SAFE_REASONS = {
    "none",
    "inventory_unavailable",
    "inventory_invalid_response",
    "service_unavailable",
    "database_error",
    "item_not_found",
    "insufficient_inventory",
    "order_persistence_failure",
}


class LokiResponseError(ValueError):
    """Raised for malformed or rejected Loki responses."""


class LokiClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def collect(
        self, window: AnalysisWindow, context: IncidentAnalysisContext
    ) -> SourceResult[tuple[LogEntry, ...]]:
        try:
            response = await self._client.get(
                "/loki/api/v1/query_range",
                params={
                    "query": LOKI_QUERY,
                    "start": int(window.start.timestamp() * 1_000_000_000),
                    "end": int(window.end.timestamp() * 1_000_000_000),
                    "limit": MAX_LOG_ENTRIES,
                    "direction": "forward",
                },
            )
            response.raise_for_status()
            entries, malformed = parse_loki_response(
                response.json(), set(context.request_ids), set(context.trace_ids)
            )
        except (httpx.HTTPError, ValueError, TypeError):
            return SourceResult(
                SourceStatus.UNAVAILABLE,
                (),
                ("Loki telemetry is unavailable",),
            )
        warnings: list[str] = []
        status = SourceStatus.AVAILABLE
        if malformed:
            status = SourceStatus.PARTIAL
            warnings.append(f"Skipped {malformed} malformed Loki log entries")
        if not entries:
            warnings.append("No incident-correlated Loki logs were found")
        return SourceResult(status, entries, tuple(warnings))


def parse_loki_response(
    payload: Any,
    request_ids: set[str],
    trace_ids: set[str],
) -> tuple[tuple[LogEntry, ...], int]:
    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        raise LokiResponseError("Loki returned a failed response")
    data = payload.get("data")
    if not isinstance(data, Mapping) or data.get("resultType") != "streams":
        raise LokiResponseError("Loki result type is not streams")
    streams = data.get("result")
    if not isinstance(streams, list):
        raise LokiResponseError("Loki result is malformed")
    entries: list[LogEntry] = []
    seen: set[tuple[int, str, str]] = set()
    malformed = 0
    for stream in streams:
        if len(entries) >= MAX_LOG_ENTRIES:
            break
        if not isinstance(stream, Mapping):
            malformed += 1
            continue
        labels = stream.get("stream")
        values = stream.get("values")
        if not isinstance(labels, Mapping) or not isinstance(values, list):
            malformed += 1
            continue
        label_service = str(labels.get("service", ""))
        for value in values:
            if not isinstance(value, list) or len(value) != 2:
                malformed += 1
                continue
            try:
                timestamp_ns = int(value[0])
                line = json.loads(value[1])
            except (TypeError, ValueError, json.JSONDecodeError):
                malformed += 1
                continue
            if not isinstance(line, Mapping):
                malformed += 1
                continue
            request_id = _optional_string(line.get("request_id"))
            trace_id = _optional_string(line.get("trace_id"))
            if request_id not in request_ids and trace_id not in trace_ids:
                continue
            service = _optional_string(line.get("service")) or label_service
            deduplication_key = (timestamp_ns, service, value[1])
            if deduplication_key in seen:
                continue
            seen.add(deduplication_key)
            category = _optional_string(line.get("message")) or "unknown"
            if category not in KNOWN_CATEGORIES:
                category = "other"
            reason = _optional_string(line.get("reason", line.get("failure_reason")))
            entries.append(
                LogEntry(
                    timestamp_ns=timestamp_ns,
                    service=service,
                    category=category,
                    level=_optional_string(line.get("level")),
                    request_id=request_id,
                    trace_id=trace_id,
                    status_code=_optional_int(line.get("status_code")),
                    duration_ms=_optional_float(line.get("duration_ms")),
                    reason=reason if reason in SAFE_REASONS else None,
                )
            )
            if len(entries) >= MAX_LOG_ENTRIES:
                break
    return tuple(
        sorted(entries, key=lambda item: (item.timestamp_ns, item.service))
    ), malformed


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None

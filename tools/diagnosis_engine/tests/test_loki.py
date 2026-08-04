import json

import httpx
import pytest

from rootlens_diagnosis.incident_context import (
    AnalysisWindow,
    IncidentAnalysisContext,
)
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.telemetry.loki import LokiClient, parse_loki_response


def test_loki_correlates_deduplicates_and_skips_malformed_lines() -> None:
    line = json.dumps(
        {
            "service": "order",
            "message": "request_completed",
            "request_id": "wanted",
            "trace_id": "a" * 32,
            "status_code": 503,
            "duration_ms": 12.5,
            "level": "ERROR",
            "exception": "must never be retained",
        }
    )
    payload = {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"service": "order"},
                    "values": [
                        ["2", line],
                        ["2", line],
                        ["3", "not-json"],
                        ["4", json.dumps({"request_id": "unrelated"})],
                    ],
                }
            ],
        },
    }

    entries, malformed = parse_loki_response(payload, {"wanted"}, {"a" * 32})

    assert len(entries) == 1
    assert entries[0].status_code == 503
    assert entries[0].request_id == "wanted"
    assert not hasattr(entries[0], "exception")
    assert malformed == 1


@pytest.mark.asyncio
async def test_unavailable_loki_has_distinct_status_and_warning() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    context = IncidentAnalysisContext(
        started_at="2026-08-03T20:00:00Z",
        ended_at="2026-08-03T20:00:20Z",
        request_ids=("request-1",),
        trace_ids=(),
        total_requests=1,
    )
    window = AnalysisWindow(start=context.started_at, end=context.ended_at)
    async with httpx.AsyncClient(
        base_url="http://loki.test", transport=httpx.MockTransport(handler)
    ) as client:
        result = await LokiClient(client).collect(window, context)
    assert result.status is SourceStatus.UNAVAILABLE
    assert result.warnings == ("Loki telemetry is unavailable",)

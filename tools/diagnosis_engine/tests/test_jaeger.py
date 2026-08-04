import httpx
import pytest

from rootlens_diagnosis.incident_context import AnalysisWindow
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.telemetry.jaeger import (
    JaegerClient,
    parse_jaeger_v3_response,
    valid_trace_id,
)

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


def _attribute(key: str, value: object) -> dict[str, object]:
    value_key = "intValue" if isinstance(value, int) else "stringValue"
    return {"key": key, "value": {value_key: value}}


def _span(
    service: str,
    span_id: str,
    kind: str,
    duration_ms: int,
    attributes: list[dict[str, object]],
) -> dict[str, object]:
    del service
    return {
        "traceId": TRACE_ID,
        "spanId": span_id,
        "name": "safe normalized name",
        "kind": kind,
        "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": str(1_000_000_000 + duration_ms * 1_000_000),
        "attributes": attributes,
        "status": {"code": "STATUS_CODE_UNSET"},
    }


def trace_payload() -> dict[str, object]:
    return {
        "result": {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [_attribute("service.name", "rootlens-order")]
                    },
                    "scopeSpans": [
                        {"spans": [_span("order", "01", "SPAN_KIND_SERVER", 1600, [])]}
                    ],
                },
                {
                    "resource": {
                        "attributes": [_attribute("service.name", "rootlens-inventory")]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                _span(
                                    "inventory",
                                    "02",
                                    "SPAN_KIND_SERVER",
                                    1500,
                                    [
                                        _attribute(
                                            "rootlens.inventory.outcome", "success"
                                        )
                                    ],
                                ),
                                _span(
                                    "inventory",
                                    "03",
                                    "SPAN_KIND_INTERNAL",
                                    20,
                                    [_attribute("db.system", "postgresql")],
                                ),
                            ]
                        }
                    ],
                },
            ]
        }
    }


def test_v3_result_envelope_services_duration_and_database() -> None:
    spans = parse_jaeger_v3_response(trace_payload(), TRACE_ID)
    assert {span.service for span in spans} == {
        "rootlens-order",
        "rootlens-inventory",
    }
    assert max(span.duration_ms for span in spans) == 1600
    assert sum("db.system" in span.attributes for span in spans) == 1
    assert all("db.statement" not in span.attributes for span in spans)


@pytest.mark.asyncio
async def test_invalid_ids_skipped_and_expired_trace_tolerated() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.url.params["start_time"] == "2026-08-03T20:00:00Z"
        assert request.url.params["end_time"] == "2026-08-03T20:01:00Z"
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://jaeger.test", transport=httpx.MockTransport(handler)
    ) as client:
        result = await JaegerClient(client).collect(
            ("invalid", TRACE_ID),
            AnalysisWindow(
                start="2026-08-03T20:00:00Z",
                end="2026-08-03T20:01:00Z",
            ),
        )

    assert valid_trace_id(TRACE_ID)
    assert not valid_trace_id("0" * 32)
    assert paths == [f"/api/v3/traces/{TRACE_ID}"]
    assert result.status is SourceStatus.PARTIAL
    assert result.data == ()

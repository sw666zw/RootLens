from datetime import UTC, datetime

import httpx
import pytest

from rootlens_diagnosis.incident_context import AnalysisWindow
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.telemetry.prometheus import (
    PrometheusClient,
    PrometheusResponseError,
    parse_prometheus_response,
)


def test_vector_matrix_zero_and_missing_are_distinct() -> None:
    vector = parse_prometheus_response(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {"status_code": "503"}, "value": [1, "0"]}],
            },
        }
    )
    matrix = parse_prometheus_response(
        {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [{"metric": {}, "values": [[1, "0"], [2, "1"]]}],
            },
        }
    )
    missing = parse_prometheus_response(
        {"status": "success", "data": {"resultType": "vector", "result": []}}
    )
    assert vector[0].value == 0
    assert [sample.value for sample in matrix] == [0, 1]
    assert missing == ()


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "error"},
        {"status": "success", "data": {"resultType": "scalar", "result": []}},
        {"status": "success", "data": {"resultType": "vector", "result": [{}]}},
    ],
)
def test_malformed_responses_are_rejected(payload: object) -> None:
    with pytest.raises(PrometheusResponseError):
        parse_prometheus_response(payload)


@pytest.mark.asyncio
async def test_client_uses_only_fixed_rootlens_queries() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        seen.append(query)
        result_type = "matrix" if request.url.path.endswith("query_range") else "vector"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"resultType": result_type, "result": []},
            },
        )

    window = AnalysisWindow(
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 3, 0, 1, tzinfo=UTC),
    )
    async with httpx.AsyncClient(
        base_url="http://prometheus.test", transport=httpx.MockTransport(handler)
    ) as client:
        result = await PrometheusClient(client).collect(window)

    assert result.status is SourceStatus.AVAILABLE
    assert len(seen) == 11
    assert all("rootlens_" in query or query.startswith('up{job="') for query in seen)
    assert not any("request-1" in query or "SAFE-SKU" in query for query in seen)

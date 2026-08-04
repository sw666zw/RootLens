"""Bounded Prometheus HTTP API adapter with a fixed query catalog."""

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from rootlens_diagnosis.incident_context import AnalysisWindow
from rootlens_diagnosis.models import SourceStatus
from rootlens_diagnosis.telemetry.models import (
    MetricSample,
    PrometheusData,
    SourceResult,
)

MAX_SERIES = 1000
MAX_SAMPLES = 5000


class PrometheusResponseError(ValueError):
    """Raised for malformed or rejected Prometheus responses."""


def _query_catalog(window_seconds: int) -> dict[str, str]:
    duration = f"{max(1, window_seconds)}s"
    return {
        "order_requests": "sum by (route, status_code) (increase("
        f"rootlens_order_http_requests_total[{duration}]))",
        "order_errors": "sum by (route, status_code) (increase("
        f"rootlens_order_http_errors_total[{duration}]))",
        "order_p95": "histogram_quantile(0.95, sum by (le) (rate("
        "rootlens_order_http_request_duration_seconds_bucket"
        f'{{route="/orders"}}[{duration}])))',
        "inventory_requests": "sum by (route, status_code) (increase("
        f"rootlens_inventory_http_requests_total[{duration}]))",
        "inventory_errors": "sum by (route, status_code) (increase("
        f"rootlens_inventory_http_errors_total[{duration}]))",
        "inventory_p95": "histogram_quantile(0.95, sum by (le) (rate("
        "rootlens_inventory_http_request_duration_seconds_bucket"
        f'{{route="/items/{{sku}}/reserve"}}[{duration}])))',
        "order_creations": "sum by (outcome, reason) (increase("
        f"rootlens_order_creations_total[{duration}]))",
        "order_transitions": "sum by (from_status, to_status) (increase("
        f"rootlens_order_status_transitions_total[{duration}]))",
        "inventory_reservations": "sum by (outcome, reason) (increase("
        f"rootlens_inventory_reservations_total[{duration}]))",
    }


class PrometheusClient:
    """Query only predetermined RootLens metric expressions."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _instant_query(
        self, expression: str, timestamp: float
    ) -> tuple[MetricSample, ...]:
        response = await self._client.get(
            "/api/v1/query", params={"query": expression, "time": timestamp}
        )
        response.raise_for_status()
        return parse_prometheus_response(response.json())

    async def _range_query(
        self,
        expression: str,
        window: AnalysisWindow,
        *,
        step_seconds: int,
    ) -> tuple[MetricSample, ...]:
        response = await self._client.get(
            "/api/v1/query_range",
            params={
                "query": expression,
                "start": window.start.timestamp(),
                "end": window.end.timestamp(),
                "step": step_seconds,
            },
        )
        response.raise_for_status()
        return parse_prometheus_response(response.json())

    async def collect(self, window: AnalysisWindow) -> SourceResult[PrometheusData]:
        catalog = _query_catalog(window.seconds)
        names = list(catalog)
        tasks = [
            self._instant_query(catalog[name], window.end.timestamp()) for name in names
        ]
        tasks.extend(
            [
                self._range_query(
                    'up{job="inventory-service"}',
                    window,
                    step_seconds=max(1, min(15, window.seconds)),
                ),
                self._range_query(
                    'up{job="order-service"}',
                    window,
                    step_seconds=max(1, min(15, window.seconds)),
                ),
            ]
        )
        names.extend(["inventory_up", "order_up"])
        results = await asyncio.gather(*tasks, return_exceptions=True)
        queries: dict[str, tuple[MetricSample, ...]] = {}
        warnings: list[str] = []
        for name, result in zip(names, results, strict=True):
            if isinstance(result, BaseException):
                warnings.append(f"Prometheus query {name} was unavailable")
            else:
                queries[name] = result
        if not queries:
            return SourceResult(
                SourceStatus.UNAVAILABLE,
                PrometheusData(),
                ("Prometheus telemetry is unavailable",),
            )
        status = SourceStatus.PARTIAL if warnings else SourceStatus.AVAILABLE
        return SourceResult(status, PrometheusData(queries), tuple(warnings))


def parse_prometheus_response(payload: Any) -> tuple[MetricSample, ...]:
    """Validate vector or matrix response data and cap normalized samples."""
    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        raise PrometheusResponseError("Prometheus returned a failed response")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise PrometheusResponseError("Prometheus response has no data object")
    result_type = data.get("resultType")
    result = data.get("result")
    if result_type not in {"vector", "matrix"} or not isinstance(result, list):
        raise PrometheusResponseError("Prometheus result type is not supported")
    if len(result) > MAX_SERIES:
        raise PrometheusResponseError("Prometheus returned too many series")
    samples: list[MetricSample] = []
    for series in result:
        if not isinstance(series, Mapping) or not isinstance(
            series.get("metric"), Mapping
        ):
            raise PrometheusResponseError("Prometheus series is malformed")
        labels = {str(key): str(value) for key, value in series["metric"].items()}
        raw_values = (
            [series.get("value")] if result_type == "vector" else series.get("values")
        )
        if not isinstance(raw_values, list):
            raise PrometheusResponseError("Prometheus samples are malformed")
        for raw in raw_values:
            if not isinstance(raw, list) or len(raw) != 2:
                raise PrometheusResponseError("Prometheus sample is malformed")
            try:
                sample = MetricSample(labels, float(raw[0]), float(raw[1]))
            except (TypeError, ValueError) as error:
                raise PrometheusResponseError(
                    "Prometheus sample is not numeric"
                ) from error
            samples.append(sample)
            if len(samples) > MAX_SAMPLES:
                raise PrometheusResponseError("Prometheus returned too many samples")
    return tuple(samples)

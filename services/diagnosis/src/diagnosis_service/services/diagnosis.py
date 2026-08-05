"""Direct orchestration of the existing diagnosis-engine library."""

import asyncio
from dataclasses import replace
from pathlib import Path

import httpx
from rootlens_diagnosis.config import DiagnosisConfig
from rootlens_diagnosis.engine import DiagnosisEngine
from rootlens_diagnosis.extractors.logs import extract_logs
from rootlens_diagnosis.extractors.metrics import extract_metrics
from rootlens_diagnosis.extractors.traces import extract_traces
from rootlens_diagnosis.incident_context import (
    AnalysisWindow,
    IncidentAnalysisContext,
    load_analysis_context,
    normalized_window,
)
from rootlens_diagnosis.models import DiagnosisReport, SourceStatus
from rootlens_diagnosis.reports import write_diagnosis_report
from rootlens_diagnosis.telemetry.jaeger import JaegerClient
from rootlens_diagnosis.telemetry.loki import LokiClient
from rootlens_diagnosis.telemetry.models import (
    LogFeatures,
    MetricsFeatures,
    NormalizedTelemetry,
    SourceResult,
    TraceFeatures,
)
from rootlens_diagnosis.telemetry.prometheus import PrometheusClient


class DiagnosisTelemetryUnavailable(RuntimeError):
    """The requested source availability contract was not met."""

    def __init__(self, report: DiagnosisReport) -> None:
        super().__init__("telemetry unavailable")
        self.report = report


class TelemetryClients:
    """Reusable engine adapters backed by application-scoped HTTP clients."""

    def __init__(
        self,
        prometheus: httpx.AsyncClient,
        loki: httpx.AsyncClient,
        jaeger: httpx.AsyncClient,
    ) -> None:
        self.prometheus = PrometheusClient(prometheus)
        self.loki = LokiClient(loki)
        self.jaeger = JaegerClient(jaeger)


class DiagnosisService:
    def __init__(
        self,
        config: DiagnosisConfig,
        clients: TelemetryClients,
        engine: DiagnosisEngine | None = None,
    ) -> None:
        self._config = config
        self._clients = clients
        self._engine = engine or DiagnosisEngine()

    async def diagnose(
        self,
        incident_path: Path,
        *,
        require_all_sources: bool,
        window_padding_seconds: int | None,
    ) -> DiagnosisReport:
        context = load_analysis_context(incident_path)
        config = replace(
            self._config,
            require_all_sources=require_all_sources,
            window_padding_seconds=(
                self._config.window_padding_seconds
                if window_padding_seconds is None
                else window_padding_seconds
            ),
        )
        window = normalized_window(context, config.window_padding_seconds)
        telemetry = await self._collect(window, context)
        report = self._engine.analyze(context, window, telemetry)
        write_diagnosis_report(report, config.prepare_output_dir())
        statuses = report.telemetry_coverage.model_dump().values()
        if report.telemetry_coverage.available_source_count() == 0 or (
            require_all_sources
            and any(status is SourceStatus.UNAVAILABLE for status in statuses)
        ):
            raise DiagnosisTelemetryUnavailable(report)
        return report

    async def _collect(
        self, window: AnalysisWindow, context: IncidentAnalysisContext
    ) -> NormalizedTelemetry:
        metrics_raw, logs_raw, traces_raw = await asyncio.gather(
            self._clients.prometheus.collect(window),
            self._clients.loki.collect(window, context),
            self._clients.jaeger.collect(context.trace_ids, window),
        )
        return NormalizedTelemetry(
            metrics=SourceResult(
                metrics_raw.status,
                extract_metrics(metrics_raw.data),
                metrics_raw.warnings,
            ),
            logs=SourceResult(
                logs_raw.status, extract_logs(logs_raw.data), logs_raw.warnings
            ),
            traces=SourceResult(
                traces_raw.status,
                extract_traces(traces_raw.data),
                traces_raw.warnings,
            ),
        )


def unavailable_telemetry() -> NormalizedTelemetry:
    """Convenient fake input for service tests."""
    return NormalizedTelemetry(
        SourceResult(SourceStatus.UNAVAILABLE, MetricsFeatures()),
        SourceResult(SourceStatus.UNAVAILABLE, LogFeatures()),
        SourceResult(SourceStatus.UNAVAILABLE, TraceFeatures()),
    )

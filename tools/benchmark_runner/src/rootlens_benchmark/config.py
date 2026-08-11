"""Validated benchmark configuration."""

import os
from dataclasses import dataclass
from pathlib import Path

from rootlens_diagnosis.config import DiagnosisConfig
from rootlens_scenarios.models import ScenarioName

DEFAULT_SCENARIOS = tuple(ScenarioName)
DEFAULT_BENCHMARK_OUTPUT_DIR = Path("runtime/benchmarks")
DEFAULT_INCIDENT_OUTPUT_DIR = Path("runtime/incidents")


@dataclass(frozen=True)
class BenchmarkConfig:
    """All inputs required for one benchmark invocation."""

    scenarios: tuple[ScenarioName, ...] = DEFAULT_SCENARIOS
    repetitions: int = 3
    requests: int = 10
    concurrency: int = 5
    latency_delay_ms: int = 1500
    telemetry_settle_seconds: int = 15
    output_dir: Path = DEFAULT_BENCHMARK_OUTPUT_DIR
    incident_output_dir: Path = DEFAULT_INCIDENT_OUTPUT_DIR
    require_all_sources: bool = False

    def validate(self) -> None:
        if not self.scenarios:
            raise ValueError("at least one scenario is required")
        if len(set(self.scenarios)) != len(self.scenarios):
            raise ValueError("scenarios must not contain duplicates")
        for name, value in (
            ("repetitions", self.repetitions),
            ("requests", self.requests),
            ("concurrency", self.concurrency),
            ("latency-delay-ms", self.latency_delay_ms),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.concurrency > self.requests:
            raise ValueError("concurrency may not exceed requests")
        if self.latency_delay_ms > 10_000:
            raise ValueError("latency-delay-ms must not exceed 10000")
        if self.telemetry_settle_seconds < 0:
            raise ValueError("telemetry-settle-seconds must be non-negative")

    @classmethod
    def from_values(
        cls,
        *,
        scenarios: tuple[ScenarioName, ...],
        repetitions: int,
        requests: int,
        concurrency: int,
        latency_delay_ms: int,
        telemetry_settle_seconds: int,
        output_dir: Path | None,
        require_all_sources: bool,
    ) -> "BenchmarkConfig":
        config = cls(
            scenarios=scenarios,
            repetitions=repetitions,
            requests=requests,
            concurrency=concurrency,
            latency_delay_ms=latency_delay_ms,
            telemetry_settle_seconds=telemetry_settle_seconds,
            output_dir=output_dir
            or Path(
                os.getenv(
                    "ROOTLENS_BENCHMARK_OUTPUT_DIR",
                    str(DEFAULT_BENCHMARK_OUTPUT_DIR),
                )
            ),
            incident_output_dir=Path(
                os.getenv(
                    "ROOTLENS_INCIDENT_OUTPUT_DIR",
                    str(DEFAULT_INCIDENT_OUTPUT_DIR),
                )
            ),
            require_all_sources=require_all_sources,
        )
        config.validate()
        return config

    def diagnosis_config(self) -> DiagnosisConfig:
        return DiagnosisConfig.from_environment(
            require_all_sources=self.require_all_sources
        )

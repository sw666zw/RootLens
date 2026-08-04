"""Validated environment and command-line configuration."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PROMETHEUS_URL = "http://localhost:9090"
DEFAULT_LOKI_URL = "http://localhost:3100"
DEFAULT_JAEGER_URL = "http://localhost:16686"
DEFAULT_OUTPUT_DIR = Path("runtime/diagnoses")
DEFAULT_PADDING_SECONDS = 15
DEFAULT_TIMEOUT_SECONDS = 10.0


def validate_url(value: str, name: str) -> str:
    """Validate an HTTP(S) base URL without exposing it in errors."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name} must be a valid HTTP or HTTPS URL")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must be a base URL without query or fragment")
    return value.rstrip("/")


def _integer_environment(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _float_environment(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error


@dataclass(frozen=True)
class DiagnosisConfig:
    """Runtime settings shared by all telemetry clients."""

    prometheus_url: str
    loki_url: str
    jaeger_url: str
    output_dir: Path
    window_padding_seconds: int
    timeout_seconds: float
    require_all_sources: bool = False

    @classmethod
    def from_environment(
        cls,
        *,
        prometheus_url: str | None = None,
        loki_url: str | None = None,
        jaeger_url: str | None = None,
        output_dir: Path | None = None,
        window_padding_seconds: int | None = None,
        require_all_sources: bool = False,
    ) -> "DiagnosisConfig":
        padding = (
            window_padding_seconds
            if window_padding_seconds is not None
            else _integer_environment(
                "ROOTLENS_DIAGNOSIS_WINDOW_PADDING_SECONDS",
                DEFAULT_PADDING_SECONDS,
            )
        )
        timeout = _float_environment(
            "ROOTLENS_TELEMETRY_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
        )
        if padding < 0:
            raise ValueError("window padding must be non-negative")
        if timeout <= 0:
            raise ValueError("telemetry timeout must be positive")
        return cls(
            prometheus_url=validate_url(
                prometheus_url or os.getenv("PROMETHEUS_URL", DEFAULT_PROMETHEUS_URL),
                "Prometheus URL",
            ),
            loki_url=validate_url(
                loki_url or os.getenv("LOKI_URL", DEFAULT_LOKI_URL), "Loki URL"
            ),
            jaeger_url=validate_url(
                jaeger_url or os.getenv("JAEGER_QUERY_URL", DEFAULT_JAEGER_URL),
                "Jaeger URL",
            ),
            output_dir=output_dir
            or Path(
                os.getenv("ROOTLENS_DIAGNOSIS_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))
            ),
            window_padding_seconds=padding,
            timeout_seconds=timeout,
            require_all_sources=require_all_sources,
        )

    def prepare_output_dir(self) -> Path:
        """Create and verify the configured output directory."""
        return prepare_output_directory(self.output_dir)


def prepare_output_directory(path: Path) -> Path:
    """Create and validate output without loading unrelated telemetry settings."""
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or not os.access(path, os.W_OK):
        raise ValueError("diagnosis output directory is not writable")
    return path

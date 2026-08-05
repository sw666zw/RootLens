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
DEFAULT_EXPLANATION_PROVIDER = "template"
DEFAULT_EXPLANATION_OUTPUT_DIR = Path("runtime/explanations")
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0
DEFAULT_LLM_MAX_OUTPUT_TOKENS = 1200
DEFAULT_OPENAI_MODEL = "gpt-5-mini"


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


def _boolean_environment(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


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


@dataclass(frozen=True)
class ExplanationConfig:
    """Validated settings for explaining an existing diagnosis report."""

    provider: str
    llm_enabled: bool
    output_dir: Path
    timeout_seconds: float
    max_output_tokens: int
    openai_api_key: str | None
    openai_model: str | None

    @classmethod
    def from_environment(
        cls,
        *,
        output_dir: Path | None = None,
    ) -> "ExplanationConfig":
        provider = (
            os.getenv("ROOTLENS_EXPLANATION_PROVIDER", DEFAULT_EXPLANATION_PROVIDER)
            .strip()
            .lower()
        )
        if provider not in {"template", "openai"}:
            raise ValueError("unsupported explanation provider")
        llm_enabled = _boolean_environment("ROOTLENS_LLM_ENABLED", False)
        timeout = _float_environment(
            "ROOTLENS_LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS
        )
        max_tokens = _integer_environment(
            "ROOTLENS_LLM_MAX_OUTPUT_TOKENS", DEFAULT_LLM_MAX_OUTPUT_TOKENS
        )
        if timeout <= 0:
            raise ValueError("LLM timeout must be positive")
        if max_tokens <= 0:
            raise ValueError("LLM max output tokens must be positive")

        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        if provider == "openai":
            if not llm_enabled:
                raise ValueError("OpenAI explanation provider is disabled")
            if not api_key or not api_key.strip():
                raise ValueError("OpenAI explanation provider requires OPENAI_API_KEY")
            if not model or not model.strip():
                raise ValueError("OpenAI explanation provider requires OPENAI_MODEL")

        return cls(
            provider=provider,
            llm_enabled=llm_enabled,
            output_dir=output_dir
            or Path(
                os.getenv(
                    "ROOTLENS_EXPLANATION_OUTPUT_DIR",
                    str(DEFAULT_EXPLANATION_OUTPUT_DIR),
                )
            ),
            timeout_seconds=timeout,
            max_output_tokens=max_tokens,
            openai_api_key=api_key.strip() if api_key else None,
            openai_model=model.strip() if model else None,
        )

    def prepare_output_dir(self) -> Path:
        return prepare_output_directory(self.output_dir)


def prepare_output_directory(path: Path) -> Path:
    """Create and validate output without loading unrelated telemetry settings."""
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or not os.access(path, os.W_OK):
        raise ValueError("output directory is not writable")
    return path

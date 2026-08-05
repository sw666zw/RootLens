"""Validated environment configuration for the Diagnosis Service."""

import os
from dataclasses import dataclass
from pathlib import Path

from rootlens_diagnosis.config import DiagnosisConfig, ExplanationConfig


def _port() -> int:
    try:
        value = int(os.getenv("DIAGNOSIS_SERVICE_PORT", "8002"))
    except ValueError as error:
        raise ValueError("DIAGNOSIS_SERVICE_PORT must be an integer.") from error
    if not 1 <= value <= 65535:
        raise ValueError("DIAGNOSIS_SERVICE_PORT must be between 1 and 65535.")
    return value


@dataclass(frozen=True)
class Settings:
    """Application settings plus existing engine settings."""

    host: str
    port: int
    incident_output_dir: Path
    diagnosis: DiagnosisConfig
    explanation: ExplanationConfig

    @classmethod
    def from_environment(cls) -> "Settings":
        host = os.getenv("DIAGNOSIS_SERVICE_HOST", "0.0.0.0").strip()
        if not host:
            raise ValueError("DIAGNOSIS_SERVICE_HOST must not be blank.")
        return cls(
            host=host,
            port=_port(),
            incident_output_dir=Path(
                os.getenv("ROOTLENS_INCIDENT_OUTPUT_DIR", "runtime/incidents")
            ),
            diagnosis=DiagnosisConfig.from_environment(),
            explanation=ExplanationConfig.from_environment(),
        )

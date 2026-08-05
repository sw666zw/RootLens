"""Atomic deterministic JSON report persistence."""

import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from rootlens_diagnosis.explanation_models import (
    ExplanationReport,
    ExplanationValidationReport,
)
from rootlens_diagnosis.models import DiagnosisReport, EvaluationReport


def write_diagnosis_report(report: DiagnosisReport, output_dir: Path) -> Path:
    return _write_model_atomic(report, output_dir / f"{report.diagnosis_id}.json")


def write_evaluation_report(report: EvaluationReport, output_dir: Path) -> Path:
    return _write_model_atomic(
        report, output_dir / f"{report.evaluation_id}.evaluation.json"
    )


def write_explanation_report(report: ExplanationReport, output_dir: Path) -> Path:
    return _write_model_atomic(report, output_dir / f"{report.explanation_id}.json")


def write_explanation_validation_report(
    report: ExplanationValidationReport, output_dir: Path
) -> Path:
    return _write_model_atomic(
        report, output_dir / f"{report.validation_id}.validation.json"
    )


def _write_model_atomic(model: BaseModel, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    payload = (
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    try:
        with temporary.open("x", encoding="utf-8") as report_file:
            report_file.write(payload)
            report_file.flush()
            os.fsync(report_file.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination

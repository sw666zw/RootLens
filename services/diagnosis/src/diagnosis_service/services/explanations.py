"""Explanation generation and deterministic offline validation."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rootlens_diagnosis.config import ExplanationConfig
from rootlens_diagnosis.evaluation import load_diagnosis
from rootlens_diagnosis.explanation_models import (
    ExplanationReport,
    ExplanationValidationReport,
    ProviderStatus,
)
from rootlens_diagnosis.explanation_projection import build_safe_explanation_input
from rootlens_diagnosis.explanation_providers import (
    ExplanationProvider,
    ExplanationProviderError,
    TemplateExplanationProvider,
    configured_provider,
)
from rootlens_diagnosis.explanation_validation import validate_explanation_file
from rootlens_diagnosis.explanations import (
    create_explanation_report,
    generate_with_provider,
)
from rootlens_diagnosis.reports import (
    write_explanation_report,
    write_explanation_validation_report,
)

ProviderFactory = Callable[[str, ExplanationConfig], ExplanationProvider]


class OpenAIDisabledError(RuntimeError):
    """OpenAI was requested without explicit server enablement."""


def _provider_factory(name: str, config: ExplanationConfig) -> ExplanationProvider:
    if name == "template":
        return TemplateExplanationProvider()
    return configured_provider(replace(config, provider="openai"))


class ExplanationService:
    def __init__(
        self,
        config: ExplanationConfig,
        provider_factory: ProviderFactory = _provider_factory,
    ) -> None:
        self._config = config
        self._provider_factory = provider_factory

    def explain(
        self,
        diagnosis_path: Path,
        *,
        provider_name: str | None,
        allow_template_fallback: bool,
    ) -> ExplanationReport:
        name = provider_name or self._config.provider
        if name not in {"template", "openai"}:
            raise ValueError("unsupported provider")
        if name == "openai" and not self._config.llm_enabled:
            raise OpenAIDisabledError
        diagnosis = load_diagnosis(diagnosis_path)
        projection = build_safe_explanation_input(diagnosis)
        status = ProviderStatus.COMPLETED
        warnings: list[str] = []
        try:
            result = generate_with_provider(
                self._provider_factory(name, self._config), projection
            )
        except ExplanationProviderError:
            if name != "openai" or not allow_template_fallback:
                raise
            result = TemplateExplanationProvider().generate(projection)
            status = ProviderStatus.FALLBACK
            warnings.append(
                "OpenAI explanation was unavailable; explicit template fallback "
                "was used."
            )
        report = create_explanation_report(
            diagnosis,
            projection,
            result,
            provider_status=status,
            extra_warnings=warnings,
        )
        write_explanation_report(report, self._config.prepare_output_dir())
        return report

    def validate(
        self, explanation_path: Path, diagnosis_path: Path
    ) -> ExplanationValidationReport:
        report = validate_explanation_file(explanation_path, diagnosis_path)
        write_explanation_validation_report(report, self._config.prepare_output_dir())
        return report

import json
import os
from pathlib import Path

import pytest

from rootlens_diagnosis.cli import main
from rootlens_diagnosis.explanation_models import (
    ProviderMetadata,
    ProviderResult,
    SafeExplanationInput,
)
from rootlens_diagnosis.explanation_projection import build_safe_explanation_input
from rootlens_diagnosis.explanation_providers import (
    ExplanationProviderError,
    OpenAIExplanationProvider,
    TemplateExplanationProvider,
)
from rootlens_diagnosis.models import DiagnosisReport
from rootlens_diagnosis.reports import write_diagnosis_report


class FakeOpenAIProvider:
    def generate(self, projection: SafeExplanationInput) -> ProviderResult:
        template = TemplateExplanationProvider().generate(projection)
        return ProviderResult(
            narrative=template.narrative,
            metadata=ProviderMetadata(provider="openai", model="fake-model"),
        )


class FailingProvider:
    def generate(self, projection: SafeExplanationInput) -> ProviderResult:
        del projection
        raise ExplanationProviderError("safe provider failure")


def diagnosis_path(tmp_path: Path, report: DiagnosisReport) -> Path:
    return write_diagnosis_report(report, tmp_path / "diagnoses")


def test_explain_template_writes_report_and_prints_summary(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "explanations"
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "template")
    monkeypatch.setenv("ROOTLENS_LLM_ENABLED", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ROOTLENS_EXPLANATION_OUTPUT_DIR", str(output))

    result = main(["explain", str(diagnosis_path(tmp_path, diagnosis_report))])

    captured = capsys.readouterr().out
    reports = list(output.glob("explanation-*.json"))
    assert result == 0
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert "Provider: template (completed)" in captured
    assert report["headline"] in captured
    assert f"Report: {reports[0]}" in captured


def test_template_cli_is_isolated_from_openai_shell_environment(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert os.environ["ROOTLENS_EXPLANATION_PROVIDER"] == "template"
    assert os.environ["ROOTLENS_LLM_ENABLED"] == "false"
    assert "OPENAI_API_KEY" not in os.environ

    def fail_if_openai_runs(
        _provider: OpenAIExplanationProvider,
        _projection: SafeExplanationInput,
    ) -> ProviderResult:
        raise AssertionError("template test attempted an OpenAI request")

    monkeypatch.setattr(OpenAIExplanationProvider, "generate", fail_if_openai_runs)
    output = tmp_path / "isolated-explanations"
    monkeypatch.setenv("ROOTLENS_EXPLANATION_OUTPUT_DIR", str(output))

    result = main(["explain", str(diagnosis_path(tmp_path, diagnosis_report))])

    report = json.loads(next(output.glob("explanation-*.json")).read_text())
    assert result == 0
    assert report["provider"] == "template"
    assert report["provider_status"] == "completed"


def test_explain_fake_openai_writes_openai_report(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "explanations"
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "openai")
    monkeypatch.setenv("ROOTLENS_LLM_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-value")
    monkeypatch.setenv("ROOTLENS_EXPLANATION_OUTPUT_DIR", str(output))
    monkeypatch.setattr(
        "rootlens_diagnosis.cli.configured_provider",
        lambda config: FakeOpenAIProvider(),
    )

    result = main(["explain", str(diagnosis_path(tmp_path, diagnosis_report))])

    report = json.loads(next(output.glob("explanation-*.json")).read_text())
    assert result == 0
    assert report["provider"] == "openai"
    assert report["provider_status"] == "completed"
    assert "sk-private-value" not in json.dumps(report)


def test_provider_failure_falls_back_only_with_explicit_flag(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "explanations"
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "openai")
    monkeypatch.setenv("ROOTLENS_LLM_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-value")
    monkeypatch.setenv("ROOTLENS_EXPLANATION_OUTPUT_DIR", str(output))
    monkeypatch.setattr(
        "rootlens_diagnosis.cli.configured_provider", lambda config: FailingProvider()
    )
    path = diagnosis_path(tmp_path, diagnosis_report)

    without_fallback = main(["explain", str(path)])
    assert without_fallback == 2
    assert list(output.glob("*.json")) == []

    with_fallback = main(["explain", str(path), "--allow-template-fallback"])
    report = json.loads(next(output.glob("explanation-*.json")).read_text())
    assert with_fallback == 0
    assert report["provider"] == "template"
    assert report["provider_status"] == "fallback"
    assert any("fallback" in item.lower() for item in report["warnings"])


def test_cli_prints_safe_openai_diagnostics_without_generic_replacement(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "openai")
    monkeypatch.setenv("ROOTLENS_LLM_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-value")
    diagnostic = (
        "OpenAI API error: status_code=400; type=invalid_request_error; "
        "code=unsupported_parameter; message=Unsupported parameter"
    )

    class DiagnosticProvider:
        def generate(self, projection: SafeExplanationInput) -> ProviderResult:
            del projection
            raise ExplanationProviderError(diagnostic)

    monkeypatch.setattr(
        "rootlens_diagnosis.cli.configured_provider",
        lambda config: DiagnosticProvider(),
    )

    result = main(["explain", str(diagnosis_path(tmp_path, diagnosis_report))])

    output = capsys.readouterr().out
    assert result == 2
    assert diagnostic in output
    assert "OpenAI explanation request failed" not in output
    assert "sk-private-value" not in output


def test_openai_configuration_error_never_falls_back_or_writes(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "explanations"
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "openai")
    monkeypatch.setenv("ROOTLENS_LLM_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-value")
    monkeypatch.setenv("OPENAI_MODEL", "")
    monkeypatch.setenv("ROOTLENS_EXPLANATION_OUTPUT_DIR", str(output))

    result = main(
        [
            "explain",
            str(diagnosis_path(tmp_path, diagnosis_report)),
            "--allow-template-fallback",
        ]
    )

    assert result == 2
    assert list(output.glob("*.json")) == []
    assert "sk-private-value" not in capsys.readouterr().out


def test_validate_explanation_prints_pass_and_fail_and_never_calls_provider(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "explanations"
    monkeypatch.setenv("ROOTLENS_EXPLANATION_OUTPUT_DIR", str(output))
    diagnosis = diagnosis_path(tmp_path, diagnosis_report)
    assert main(["explain", str(diagnosis)]) == 0
    explanation = next(output.glob("explanation-*.json"))
    monkeypatch.setattr(
        "rootlens_diagnosis.cli.configured_provider",
        lambda config: (_ for _ in ()).throw(AssertionError("provider called")),
    )
    capsys.readouterr()

    passed = main(["validate-explanation", str(explanation), str(diagnosis)])
    assert passed == 0
    assert capsys.readouterr().out.startswith("PASS\n")

    payload = json.loads(explanation.read_text())
    payload["confidence"] = 0.001
    explanation.write_text(json.dumps(payload), encoding="utf-8")
    failed = main(["validate-explanation", str(explanation), str(diagnosis)])
    assert failed == 1
    assert capsys.readouterr().out.startswith("FAIL\n")
    assert len(list(output.glob("*.validation.json"))) == 2


def test_explain_does_not_require_ground_truth_or_mutate_diagnosis(
    tmp_path: Path,
    diagnosis_report: DiagnosisReport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "explanations"
    monkeypatch.setenv("ROOTLENS_EXPLANATION_OUTPUT_DIR", str(output))
    path = diagnosis_path(tmp_path, diagnosis_report)
    before = path.read_bytes()

    assert main(["explain", str(path)]) == 0

    assert path.read_bytes() == before
    projection = build_safe_explanation_input(diagnosis_report)
    assert projection.diagnosis_id == diagnosis_report.diagnosis_id

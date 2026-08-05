import os

import pytest

from rootlens_diagnosis.config import ExplanationConfig


def test_template_is_default_and_llm_is_disabled() -> None:
    config = ExplanationConfig.from_environment()

    assert config.provider == "template"
    assert config.llm_enabled is False
    assert config.openai_api_key is None


def test_openai_disabled_fails_before_client_can_be_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-value")

    with pytest.raises(ValueError, match="disabled") as captured:
        ExplanationConfig.from_environment()

    assert "sk-private-value" not in str(captured.value)


def test_openai_requires_key_and_nonempty_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROOTLENS_EXPLANATION_PROVIDER", "openai")
    monkeypatch.setenv("ROOTLENS_LLM_ENABLED", "true")

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        ExplanationConfig.from_environment()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-value")
    monkeypatch.setenv("OPENAI_MODEL", " ")
    with pytest.raises(ValueError, match="OPENAI_MODEL") as captured:
        ExplanationConfig.from_environment()
    assert "sk-private-value" not in str(captured.value)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("ROOTLENS_EXPLANATION_PROVIDER", "other", "unsupported"),
        ("ROOTLENS_LLM_ENABLED", "sometimes", "true or false"),
        ("ROOTLENS_LLM_TIMEOUT_SECONDS", "0", "timeout must be positive"),
        ("ROOTLENS_LLM_MAX_OUTPUT_TOKENS", "-1", "tokens must be positive"),
    ],
)
def test_invalid_configuration_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-private-value")

    with pytest.raises(ValueError, match=message) as captured:
        ExplanationConfig.from_environment()

    assert os.environ["OPENAI_API_KEY"] not in str(captured.value)

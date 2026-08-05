import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from rootlens_diagnosis.config import ExplanationConfig
from rootlens_diagnosis.explanation_models import (
    ExplanationNarrative,
    SafeExplanationInput,
)
from rootlens_diagnosis.explanation_projection import build_safe_explanation_input
from rootlens_diagnosis.explanation_providers import (
    ExplanationProviderError,
    OpenAIExplanationProvider,
    TemplateExplanationProvider,
)
from rootlens_diagnosis.models import DiagnosisReport


def narrative_payload(evidence_id: str) -> dict[str, object]:
    return {
        "headline": "Evidence-grounded explanation",
        "executive_summary": "The deterministic diagnosis is summarized.",
        "impact": "The supplied evidence supports only the diagnosed system impact.",
        "causal_chain": ["The diagnosed condition produced the observed symptom."],
        "evidence_based_claims": [
            {
                "claim": "A normalized signal was observed.",
                "evidence_refs": [evidence_id],
            }
        ],
        "uncertainties": ["Confidence remains limited by the deterministic report."],
        "immediate_actions": ["Inspect the cited normalized evidence."],
        "follow_up_actions": ["Compare later telemetry after stabilization."],
        "operator_notes": None,
    }


def openai_config() -> ExplanationConfig:
    return ExplanationConfig(
        provider="openai",
        llm_enabled=True,
        output_dir=Path("runtime/explanations"),
        timeout_seconds=12,
        max_output_tokens=600,
        openai_api_key="sk-private-value",
        openai_model="gpt-5-mini",
    )


class FakeResponses:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeOpenAIAPIError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__("raw exception text must never be used")
        self.status_code = 400
        self.type = "invalid_request_error"
        self.code = "unsupported_parameter"
        self.message = message
        self.headers = {"authorization": "Bearer provider-header-secret"}
        self.response = "raw-provider-response"


def fake_client(responses: FakeResponses) -> SimpleNamespace:
    return SimpleNamespace(responses=responses)


def completed_response(payload: object) -> SimpleNamespace:
    return SimpleNamespace(
        status="completed",
        output_parsed=payload,
        output=[],
        id="resp_safe",
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def test_template_output_is_deterministic_and_cites_only_valid_evidence(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    provider = TemplateExplanationProvider()

    first = provider.generate(projection)
    second = provider.generate(projection)
    valid_ids = {item.evidence_id for item in projection.evidence}

    assert first == second
    assert first.metadata.provider == "template"
    assert all(
        set(claim.evidence_refs) <= valid_ids
        for claim in first.narrative.evidence_based_claims
    )


def test_openai_receives_only_stable_projection_and_one_strict_request(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    evidence_id = projection.evidence[0].evidence_id
    responses = FakeResponses(completed_response(narrative_payload(evidence_id)))

    result = OpenAIExplanationProvider(
        openai_config(), client=fake_client(responses)
    ).generate(projection)

    assert result.metadata.provider == "openai"
    assert result.metadata.usage is not None
    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call["text_format"] is ExplanationNarrative
    assert call["store"] is False
    assert call["max_output_tokens"] == 600
    assert call["timeout"] == 12
    assert call["reasoning"] == {"effort": "minimal"}
    assert call["text"] == {"verbosity": "low"}
    assert "tools" not in call
    assert "previous_response_id" not in call
    sent = json.loads(call["input"])
    assert sent == projection.model_dump(mode="json")
    assert "expected_root_cause" not in call["input"]
    assert "sk-private-value" not in repr(call)


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="incomplete", output_parsed=None, output=[]),
        SimpleNamespace(status="completed", output_parsed=None, output=[]),
        SimpleNamespace(
            status="completed",
            output_parsed=None,
            output=[
                SimpleNamespace(
                    content=[SimpleNamespace(type="refusal")], type="message"
                )
            ],
        ),
    ],
)
def test_incomplete_empty_and_refused_responses_fail_safely(
    diagnosis_report: DiagnosisReport, response: object
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    provider = OpenAIExplanationProvider(
        openai_config(), client=fake_client(FakeResponses(response))
    )

    with pytest.raises(ExplanationProviderError) as captured:
        provider.generate(projection)

    assert "sk-private-value" not in str(captured.value)


def test_incomplete_response_exposes_only_safe_diagnostic_fields(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    response = SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        usage=SimpleNamespace(
            input_tokens=321,
            output_tokens=4000,
            output_tokens_details=SimpleNamespace(reasoning_tokens=3975),
        ),
        output_parsed=None,
        output=[],
        raw_provider_response="raw-response-must-not-appear",
        api_key="sk-private-value",
        headers={"authorization": "secret-provider-header"},
    )
    responses = FakeResponses(response)

    with pytest.raises(ExplanationProviderError) as captured:
        OpenAIExplanationProvider(
            openai_config(), client=fake_client(responses)
        ).generate(projection)

    message = str(captured.value)
    assert len(responses.calls) == 1
    assert message == (
        "OpenAI explanation response was incomplete: status=incomplete; "
        "reason=max_output_tokens; input_tokens=321; output_tokens=4000; "
        "reasoning_tokens=3975"
    )
    for forbidden in (
        "sk-private-value",
        "raw-response-must-not-appear",
        "secret-provider-header",
        responses.calls[0]["input"],
        "You explain an existing deterministic RootLens diagnosis",
    ):
        assert forbidden not in message


def test_openai_api_error_exposes_only_sanitized_metadata(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    projection_value = projection.deterministic_summary
    error = FakeOpenAIAPIError(
        "Unsupported parameter for this model; "
        f"projection={projection_value}; key=sk-private-value"
    )
    responses = FakeResponses(error=error)

    with pytest.raises(ExplanationProviderError) as captured:
        OpenAIExplanationProvider(
            openai_config(), client=fake_client(responses)
        ).generate(projection)

    message = str(captured.value)
    assert len(responses.calls) == 1
    assert "OpenAI API error" in message
    assert "status_code=400" in message
    assert "type=invalid_request_error" in message
    assert "code=unsupported_parameter" in message
    assert "message=Unsupported parameter for this model" in message
    assert "[redacted]" in message
    for forbidden in (
        projection_value,
        "sk-private-value",
        "provider-header-secret",
        "raw-provider-response",
        "raw exception text must never be used",
        responses.calls[0]["input"],
    ):
        assert forbidden not in message


def test_pydantic_validation_error_reports_safe_field_paths(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    responses = FakeResponses(completed_response({"headline": "only one field"}))

    with pytest.raises(ExplanationProviderError) as captured:
        OpenAIExplanationProvider(
            openai_config(), client=fake_client(responses)
        ).generate(projection)

    message = str(captured.value)
    assert "OpenAI structured output validation failed" in message
    assert "exception=ValidationError" in message
    assert "executive_summary: Field required" in message
    assert "impact: Field required" in message
    assert responses.calls[0]["input"] not in message
    assert "sk-private-value" not in message


def test_structured_output_json_error_is_reported_without_raw_content(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    responses = FakeResponses(
        error=json.JSONDecodeError(
            "raw JSON included sk-private-value",
            projection.deterministic_summary,
            0,
        )
    )

    with pytest.raises(ExplanationProviderError) as captured:
        OpenAIExplanationProvider(
            openai_config(), client=fake_client(responses)
        ).generate(projection)

    assert str(captured.value) == (
        "OpenAI structured output validation failed: "
        "exception=JSONDecodeError; fields=response was not valid JSON"
    )


def test_missing_parsed_output_has_an_actionable_safe_error(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    response = SimpleNamespace(status="completed", output_parsed=None, output=[])

    with pytest.raises(ExplanationProviderError) as captured:
        OpenAIExplanationProvider(
            openai_config(), client=fake_client(FakeResponses(response))
        ).generate(projection)

    assert str(captured.value) == (
        "OpenAI explanation response contained no usable structured output"
    )


def test_timeout_and_malformed_output_fail_without_raw_exception(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    responses = FakeResponses(error=TimeoutError("sk-private-value and internal URL"))
    provider = OpenAIExplanationProvider(openai_config(), fake_client(responses))

    with pytest.raises(ExplanationProviderError) as captured:
        provider.generate(projection)
    assert len(responses.calls) == 1
    assert "sk-private-value" not in str(captured.value)

    malformed = FakeResponses(completed_response({"headline": "only one field"}))
    with pytest.raises(ExplanationProviderError, match="structured output validation"):
        OpenAIExplanationProvider(openai_config(), fake_client(malformed)).generate(
            projection
        )


def test_model_cannot_generate_protected_fields_or_unknown_evidence(
    diagnosis_report: DiagnosisReport,
) -> None:
    projection = build_safe_explanation_input(diagnosis_report)
    payload = narrative_payload(projection.evidence[0].evidence_id)
    payload["suspected_root_cause"] = "inventory_service_unavailable"

    with pytest.raises(ExplanationProviderError, match="structured output validation"):
        OpenAIExplanationProvider(
            openai_config(),
            fake_client(FakeResponses(completed_response(payload))),
        ).generate(projection)

    invented = narrative_payload("evidence-999")
    with pytest.raises(ExplanationProviderError, match="unknown evidence"):
        OpenAIExplanationProvider(
            openai_config(),
            fake_client(FakeResponses(completed_response(invented))),
        ).generate(projection)


def test_duplicate_references_normalize_and_empty_references_fail() -> None:
    payload = narrative_payload("evidence-001")
    claim = payload["evidence_based_claims"][0]  # type: ignore[index]
    claim["evidence_refs"] = ["evidence-001", "evidence-001"]  # type: ignore[index]
    narrative = ExplanationNarrative.model_validate(payload)
    assert narrative.evidence_based_claims[0].evidence_refs == ["evidence-001"]

    claim["evidence_refs"] = []  # type: ignore[index]
    with pytest.raises(ValidationError):
        ExplanationNarrative.model_validate(payload)


def test_narrative_rejects_urls_code_and_modifying_commands() -> None:
    for unsafe in (
        "See https://example.com",
        "```sh\necho unsafe\n```",
        "Run rm -rf data",
        "DELETE FROM orders",
    ):
        payload = narrative_payload("evidence-001")
        payload["immediate_actions"] = [unsafe]
        with pytest.raises(ValidationError):
            ExplanationNarrative.model_validate(payload)


def test_projection_type_contains_no_arbitrary_extra_fields(
    diagnosis_report: DiagnosisReport,
) -> None:
    payload = build_safe_explanation_input(diagnosis_report).model_dump()
    payload["scenario_name"] = "secret"
    with pytest.raises(ValidationError):
        SafeExplanationInput.model_validate(payload)


def test_provider_output_json_schema_is_strict() -> None:
    schema = ExplanationNarrative.model_json_schema()

    assert schema["additionalProperties"] is False
    claim_schema = schema["$defs"]["EvidenceBasedClaim"]
    assert claim_schema["additionalProperties"] is False

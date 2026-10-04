import json
from types import SimpleNamespace

import pytest

from traceaid.config import Settings
from traceaid.models import Diagnosis, IncidentRequest, ObservedResponse, RequestSpec, Severity
from traceaid.services.diagnosis import DiagnosisService
from traceaid.services.generators import (
    generate_corrected_curl,
    generate_pytest_test,
    generate_python_snippet,
)
from traceaid.services.llm import DemoLLMProvider, FallbackLLMProvider, OpenAIResponsesProvider

pytestmark = pytest.mark.unit


def _baseline() -> Diagnosis:
    return Diagnosis(
        severity=Severity.HIGH,
        title="Authentication was rejected",
        summary="The server returned 401.",
        confidence=0.98,
        likely_cause="The credential is invalid.",
        evidence=["Observed HTTP status: 401"],
        fix_steps=["Rotate the credential."],
        category="authentication",
    )


def test_generators_are_secret_free_and_python_is_valid() -> None:
    request = RequestSpec(
        method="POST",
        url="https://api.example.com/items?api_key=url-secret",
        headers={"Authorization": "Bearer header-secret", "Content-Type": "application/json"},
        body={"password": "body-secret", "name": "Ada"},
    )

    curl = generate_corrected_curl(request)
    snippet = generate_python_snippet(request)
    test_code = generate_pytest_test(request, ObservedResponse(status_code=401))
    all_code = curl + snippet + test_code

    assert "url-secret" not in all_code
    assert "header-secret" not in all_code
    assert "body-secret" not in all_code
    assert "\n+  " not in curl
    assert "TRACEAID_AUTHORIZATION" in snippet
    compile(snippet, "generated_snippet.py", "exec")
    compile(test_code, "generated_test.py", "exec")


@pytest.mark.asyncio
async def test_openai_provider_uses_structured_output_and_preserves_evidence() -> None:
    class Responses:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        async def parse(self, **kwargs: object) -> SimpleNamespace:
            self.kwargs = kwargs
            return SimpleNamespace(
                output_parsed={
                    "severity": "high",
                    "title": "Credential rejected",
                    "summary": "The API rejected the supplied credential.",
                    "confidence": 0.99,
                    "likely_cause": "The token is expired or has the wrong audience.",
                    "fix_steps": ["Issue a scoped replacement token."],
                    "category": "authentication",
                }
            )

    responses = Responses()
    fake_client = SimpleNamespace(responses=responses)
    provider = OpenAIResponsesProvider("test-key", client=fake_client)
    request = RequestSpec(
        method="GET",
        url="https://api.example.com?token=url-secret",
        headers={"Authorization": "Bearer header-secret"},
    )

    result = await provider.refine(
        request=request,
        observed=ObservedResponse(status_code=401, body={"api_key": "response-secret"}),
        baseline=_baseline(),
    )

    assert result.source == "ai"
    assert result.evidence == _baseline().evidence
    prompt = str(responses.kwargs["input"])
    assert "url-secret" not in prompt
    assert "header-secret" not in prompt
    assert "response-secret" not in prompt


@pytest.mark.asyncio
async def test_fallback_provider_returns_demo_diagnosis() -> None:
    class BrokenProvider:
        name = "broken"

        async def refine(self, **kwargs: object) -> Diagnosis:
            raise RuntimeError("provider unavailable")

    provider = FallbackLLMProvider(BrokenProvider(), DemoLLMProvider())
    request = RequestSpec(method="GET", url="https://api.example.com")

    result = await provider.refine(request=request, observed=None, baseline=_baseline())

    assert result.source == "demo"


@pytest.mark.asyncio
async def test_diagnosis_service_returns_complete_redacted_demo_report() -> None:
    service = DiagnosisService(Settings())
    incident = IncidentRequest(
        request=RequestSpec(
            method="GET",
            url="https://api.example.com/items?api_key=url-secret",
            headers={"Authorization": "Bearer header-secret"},
        ),
        observed=ObservedResponse(status_code=401, body={"token": "response-secret"}),
        use_ai=True,
    )

    report = await service.diagnose(incident)
    serialised = json.dumps(report.model_dump())

    assert report.mode == "demo"
    assert report.diagnosis.category == "authentication"
    assert report.artifacts.markdown_report.startswith("# TraceAid diagnosis")
    assert "url-secret" not in serialised
    assert "header-secret" not in serialised
    assert "response-secret" not in serialised

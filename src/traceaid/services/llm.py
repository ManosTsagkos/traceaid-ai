"""Optional LLM refinement built on OpenAI Responses structured outputs."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from traceaid.config import Settings
from traceaid.models import Diagnosis, ObservedResponse, ProbeResult, RequestSpec, Severity
from traceaid.services.redaction import redact_body, redact_headers, redact_request, redact_text


class LLMProviderError(RuntimeError):
    """A sanitised provider error suitable for internal fallback handling."""


class LLMProvider(Protocol):
    name: str

    async def refine(
        self,
        *,
        request: RequestSpec,
        observed: ObservedResponse | ProbeResult | None,
        baseline: Diagnosis,
        context: str | None = None,
    ) -> Diagnosis:
        """Refine a rules-based diagnosis without adding unsupported evidence."""


class DemoLLMProvider:
    """Offline provider used when no API key is configured."""

    name = "demo"

    async def refine(
        self,
        *,
        request: RequestSpec,
        observed: ObservedResponse | ProbeResult | None,
        baseline: Diagnosis,
        context: str | None = None,
    ) -> Diagnosis:
        del request, observed, context
        return baseline.model_copy(update={"source": "demo"})


class _StructuredDiagnosis(BaseModel):
    """Strict schema sent to the Responses API."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(ge=0, le=1)
    likely_cause: str = Field(min_length=1, max_length=1200)
    fix_steps: list[str] = Field(max_length=12)
    category: str = Field(min_length=1, max_length=80)


def _safe_observed(observed: ObservedResponse | ProbeResult | None) -> dict[str, Any] | None:
    if observed is None:
        return None
    if isinstance(observed, ObservedResponse):
        return {
            "status_code": observed.status_code,
            "headers": redact_headers(observed.headers),
            "body": redact_body(observed.body),
            "latency_ms": observed.latency_ms,
            "error": redact_text(observed.error) if observed.error else None,
        }
    return {
        "attempted": observed.attempted,
        "status_code": observed.status_code,
        "headers": redact_headers(observed.headers),
        "body_preview": redact_text(observed.body_preview) if observed.body_preview else None,
        "latency_ms": observed.latency_ms,
        "error": redact_text(observed.error) if observed.error else None,
        "truncated": observed.truncated,
    }


class OpenAIResponsesProvider:
    """OpenAI Responses implementation using Pydantic structured output."""

    name = "openai"

    def __init__(
        self,
        api_key: SecretStr | str,
        *,
        model: str = "gpt-4o-mini",
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        self._model = model
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise LLMProviderError("The optional OpenAI SDK is not installed.") from exc
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def refine(
        self,
        *,
        request: RequestSpec,
        observed: ObservedResponse | ProbeResult | None,
        baseline: Diagnosis,
        context: str | None = None,
    ) -> Diagnosis:
        safe_payload = {
            "request": redact_request(request).model_dump(),
            "observed": _safe_observed(observed),
            "rules_diagnosis": baseline.model_dump(),
            "user_context": redact_text(context) if context else None,
        }
        instructions = (
            "You are TraceAid, a conservative REST API diagnostician. Refine the rules-based "
            "diagnosis using only the supplied evidence. Do not claim an event, field, or server "
            "state that is absent. Never ask for or reproduce secrets. Make fixes concrete and "
            "safe. The evidence list is controlled by the application and is not part of your output."
        )
        try:
            response = await self._get_client().responses.parse(
                model=self._model,
                instructions=instructions,
                input=json.dumps(safe_payload, ensure_ascii=False, sort_keys=True),
                text_format=_StructuredDiagnosis,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise LLMProviderError("The model returned no structured diagnosis.")
            if not isinstance(parsed, _StructuredDiagnosis):
                parsed = _StructuredDiagnosis.model_validate(parsed)
        except LLMProviderError:
            raise
        except Exception as exc:  # provider/SDK exceptions must not escape to the route
            raise LLMProviderError("OpenAI diagnosis refinement failed.") from exc

        # Evidence remains deterministic and application-controlled. The model
        # may improve explanation and remediation but cannot invent citations.
        return Diagnosis(
            severity=parsed.severity,
            title=parsed.title,
            summary=parsed.summary,
            confidence=parsed.confidence,
            likely_cause=parsed.likely_cause,
            evidence=baseline.evidence,
            fix_steps=parsed.fix_steps,
            category=parsed.category,
            source="ai",
        )


class FallbackLLMProvider:
    """Use a deterministic provider whenever the primary provider fails."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or DemoLLMProvider()
        self.name = f"{primary.name}+fallback"

    async def refine(
        self,
        *,
        request: RequestSpec,
        observed: ObservedResponse | ProbeResult | None,
        baseline: Diagnosis,
        context: str | None = None,
    ) -> Diagnosis:
        try:
            return await self.primary.refine(
                request=request,
                observed=observed,
                baseline=baseline,
                context=context,
            )
        except Exception:
            return await self.fallback.refine(
                request=request,
                observed=observed,
                baseline=baseline,
                context=context,
            )


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.openai_api_key:
        return OpenAIResponsesProvider(settings.openai_api_key, model=settings.openai_model)
    return DemoLLMProvider()


__all__ = [
    "DemoLLMProvider",
    "FallbackLLMProvider",
    "LLMProvider",
    "LLMProviderError",
    "OpenAIResponsesProvider",
    "get_llm_provider",
]

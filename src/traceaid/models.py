"""Pydantic models shared by TraceAid's API and diagnosis pipeline.

The public models intentionally contain JSON-native values only.  A plain
``model_dump()`` can therefore be passed to a JSON encoder without custom
handling (timestamps are ISO-8601 strings and enums inherit from ``str``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class TraceAidModel(BaseModel):
    """Strict base model used for all public request and response objects."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RequestSpec(TraceAidModel):
    """A serialisable HTTP request description.

    Network-safety checks deliberately do not happen during model validation:
    users may analyse localhost/private requests without TraceAid ever sending
    them.  ``services.url_security`` applies the stronger policy immediately
    before an optional live probe.
    """

    method: str = Field(default="GET", min_length=1, max_length=32)
    url: str = Field(min_length=1, max_length=4096)
    headers: dict[str, str] = Field(default_factory=dict)
    body: JsonValue | None = None

    @field_validator("method")
    @classmethod
    def normalise_method(cls, value: str) -> str:
        method = value.strip().upper()
        if not method or not all(character.isalpha() or character == "-" for character in method):
            raise ValueError("method must contain only letters or hyphens")
        return method

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        url = value.strip()
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("url must use http or https")
        if not parsed.hostname:
            raise ValueError("url must include a hostname")
        return url

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        normalised: dict[str, str] = {}
        for name, header_value in value.items():
            clean_name = name.strip()
            if not clean_name or any(char in clean_name for char in "\r\n:"):
                raise ValueError("header names may not be empty or contain CR, LF, or ':'")
            if "\r" in header_value or "\n" in header_value:
                raise ValueError("header values may not contain CR or LF")
            normalised[clean_name] = header_value.strip()
        return normalised


class ObservedResponse(TraceAidModel):
    """Response or transport failure supplied by the user."""

    status_code: int | None = Field(default=None, ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    body: JsonValue | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    error: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_evidence(self) -> ObservedResponse:
        if self.status_code is None and not self.error:
            raise ValueError("observed response requires status_code or error")
        return self


class IncidentRequest(TraceAidModel):
    """Input contract for the diagnosis service and HTTP endpoint."""

    request: RequestSpec
    observed: ObservedResponse | None = None
    execute_probe: bool = False
    use_ai: bool = False
    context: str | None = Field(default=None, max_length=2000)


# API-oriented name kept as a true alias so either import has the same schema.
AnalyzeRequest = IncidentRequest


class ProbeResult(TraceAidModel):
    """Bounded, redacted result of an optional outbound request."""

    attempted: bool
    url: str
    status_code: int | None = Field(default=None, ge=100, le=599)
    headers: dict[str, str] = Field(default_factory=dict)
    body_preview: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    error: str | None = None
    truncated: bool = False
    redirect_location: str | None = None


class Diagnosis(TraceAidModel):
    """An evidence-backed primary diagnosis."""

    severity: Severity
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(ge=0, le=1)
    likely_cause: str = Field(min_length=1, max_length=1200)
    evidence: list[str] = Field(default_factory=list, max_length=12)
    fix_steps: list[str] = Field(default_factory=list, max_length=12)
    category: str = Field(default="unknown", min_length=1, max_length=80)
    source: Literal["rules", "ai", "demo"] = "rules"


class GeneratedArtifacts(TraceAidModel):
    corrected_curl: str
    python_snippet: str
    pytest_test: str
    markdown_report: str


class ReportMetadata(TraceAidModel):
    rules_version: str = "1.0"
    llm_provider: str | None = None
    probe_requested: bool = False
    probe_performed: bool = False
    warnings: list[str] = Field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _report_id() -> str:
    return f"trc_{uuid4().hex[:12]}"


class DiagnosisReport(TraceAidModel):
    """Complete, safe-to-return result from a diagnosis run."""

    id: str = Field(default_factory=_report_id)
    created_at: str = Field(default_factory=_utc_now)
    mode: Literal["rules", "probe", "ai", "hybrid", "demo"] = "rules"
    redacted_request: RequestSpec
    diagnosis: Diagnosis
    artifacts: GeneratedArtifacts
    probe: ProbeResult | None = None
    metadata: ReportMetadata = Field(default_factory=ReportMetadata)


# Backwards-friendly API name.
AnalysisReport = DiagnosisReport


__all__ = [
    "AnalysisReport",
    "AnalyzeRequest",
    "Diagnosis",
    "DiagnosisReport",
    "GeneratedArtifacts",
    "IncidentRequest",
    "ObservedResponse",
    "ProbeResult",
    "ReportMetadata",
    "RequestSpec",
    "Severity",
]

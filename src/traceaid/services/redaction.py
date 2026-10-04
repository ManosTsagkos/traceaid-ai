"""Centralised secret redaction used before logging, AI calls, and reports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from traceaid.models import RequestSpec

REDACTED = "<redacted>"

_SENSITIVE_NAMES = {
    "api-key",
    "apikey",
    "authorization",
    "client-secret",
    "cookie",
    "credential",
    "jwt",
    "password",
    "passwd",
    "proxy-authorization",
    "refresh-token",
    "secret",
    "session",
    "set-cookie",
    "token",
    "x-api-key",
}

_AUTH_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\b\s*[:=]\s*)"
    r"([^\s,;&]+)"
)


def is_sensitive_name(name: str) -> bool:
    normalised = re.sub(r"[\s_]+", "-", name.strip().casefold())
    if normalised in _SENSITIVE_NAMES:
        return True
    return normalised.endswith(("-token", "-secret", "-password", "-credential", "-api-key"))


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        str(name): REDACTED if is_sensitive_name(str(name)) else redact_text(str(value))
        for name, value in headers.items()
    }


def redact_url(url: str) -> str:
    """Redact credentials and sensitive query parameters from a URL."""

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        try:
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            port = ""
        userinfo = f"{REDACTED}@" if parsed.username is not None else ""
        netloc = f"{userinfo}{hostname}{port}"
        query_items = [
            (key, REDACTED if is_sensitive_name(key) else redact_text(value))
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
        return urlunsplit(
            (
                parsed.scheme,
                netloc,
                parsed.path,
                urlencode(query_items, doseq=True),
                parsed.fragment,
            )
        )
    except (TypeError, ValueError):
        # A malformed URL may still appear in diagnostic text. Text-level
        # redaction is safer than returning it untouched.
        return redact_text(str(url))


def redact_text(value: str) -> str:
    text = _AUTH_PATTERN.sub(lambda match: f"{match.group(1)} {REDACTED}", value)
    text = _OPENAI_KEY_PATTERN.sub(REDACTED, text)
    text = _JWT_PATTERN.sub(REDACTED, text)
    return _ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}{REDACTED}", text)


def redact_body(value: Any, *, parent_key: str | None = None) -> Any:
    """Recursively redact JSON-like data while preserving its shape."""

    if parent_key is not None and is_sensitive_name(parent_key):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(key): redact_body(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_body(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_request(request: RequestSpec) -> RequestSpec:
    """Return a deep, redacted copy of a request."""

    return RequestSpec(
        method=request.method,
        url=redact_url(request.url),
        headers=redact_headers(request.headers),
        body=redact_body(request.body),
    )


__all__ = [
    "REDACTED",
    "is_sensitive_name",
    "redact_body",
    "redact_headers",
    "redact_request",
    "redact_text",
    "redact_url",
]

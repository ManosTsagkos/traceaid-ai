"""Bounded, opt-in HTTP probe used to gather fresh failure evidence."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any

import httpx

from traceaid.config import Settings, get_settings
from traceaid.models import ProbeResult, RequestSpec
from traceaid.services.redaction import redact_headers, redact_text, redact_url
from traceaid.services.url_security import UnsafeTargetError, ValidatedTarget, validate_public_url

URLValidator = Callable[[str], Awaitable[ValidatedTarget]]

_STRIPPED_OUTBOUND_HEADERS = {
    "connection",
    "content-length",
    "forwarded",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
}


def _safe_outbound_headers(request: RequestSpec, user_agent: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.casefold() not in _STRIPPED_OUTBOUND_HEADERS
    }
    if not any(key.casefold() == "user-agent" for key in headers):
        headers["User-Agent"] = user_agent
    return headers


def _request_kwargs(request: RequestSpec) -> dict[str, Any]:
    if request.body is None:
        return {}
    if isinstance(request.body, str):
        return {"content": request.body.encode("utf-8")}
    return {"json": request.body}


def _encoded_body_size(request: RequestSpec) -> int:
    if request.body is None:
        return 0
    if isinstance(request.body, str):
        return len(request.body.encode("utf-8"))
    return len(json.dumps(request.body, ensure_ascii=False).encode("utf-8"))


class ProbeClient:
    """Perform one public HTTP request under strict safety and size limits."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        url_validator: URLValidator | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._transport = transport
        self._url_validator = url_validator or validate_public_url

    async def execute(self, request: RequestSpec) -> ProbeResult:
        safe_url = redact_url(request.url)
        if not self.settings.enable_live_probes:
            return ProbeResult(
                attempted=False,
                url=safe_url,
                error="Live probes are disabled by server configuration.",
            )

        if _encoded_body_size(request) > self.settings.max_response_bytes:
            return ProbeResult(
                attempted=False,
                url=safe_url,
                error="Request body exceeds the configured probe size limit.",
            )

        try:
            await self._url_validator(request.url)
        except UnsafeTargetError as exc:
            return ProbeResult(
                attempted=False,
                url=safe_url,
                error=f"Blocked by SSRF safety policy: {redact_text(str(exc))}",
            )

        headers = _safe_outbound_headers(request, self.settings.user_agent)
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        started = perf_counter()

        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    request.method,
                    request.url,
                    headers=headers,
                    **_request_kwargs(request),
                ) as response,
            ):
                collected = bytearray()
                truncated = False
                async for chunk in response.aiter_bytes():
                    remaining = self.settings.max_response_bytes - len(collected)
                    if len(chunk) > remaining:
                        collected.extend(chunk[:remaining])
                        truncated = True
                        break
                    collected.extend(chunk)
                elapsed_ms = round((perf_counter() - started) * 1000, 2)
                encoding = response.encoding or "utf-8"
                preview = bytes(collected).decode(encoding, errors="replace")
                location = response.headers.get("location")
                return ProbeResult(
                    attempted=True,
                    url=safe_url,
                    status_code=response.status_code,
                    headers=redact_headers(dict(response.headers)),
                    body_preview=redact_text(preview),
                    latency_ms=elapsed_ms,
                    truncated=truncated,
                    redirect_location=redact_url(location) if location else None,
                )
        except httpx.TimeoutException:
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            return ProbeResult(
                attempted=True,
                url=safe_url,
                latency_ms=elapsed_ms,
                error=f"Request timed out after {self.settings.request_timeout_seconds:g} seconds.",
            )
        except httpx.RequestError as exc:
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            return ProbeResult(
                attempted=True,
                url=safe_url,
                latency_ms=elapsed_ms,
                error=redact_text(f"{exc.__class__.__name__}: {exc}")[:500],
            )


__all__ = ["ProbeClient", "URLValidator"]

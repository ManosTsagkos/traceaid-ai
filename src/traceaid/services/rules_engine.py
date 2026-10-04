"""Deterministic, evidence-first diagnosis rules."""

from __future__ import annotations

import json
from collections.abc import Mapping

from traceaid.models import Diagnosis, ObservedResponse, ProbeResult, RequestSpec, Severity
from traceaid.services.redaction import redact_body, redact_text, redact_url

RULES_VERSION = "1.0"
ResponseEvidence = ObservedResponse | ProbeResult


def _header(headers: Mapping[str, str], name: str) -> str | None:
    needle = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == needle), None)


def _body_text(response: ResponseEvidence | None) -> str:
    if response is None:
        return ""
    body = response.body if isinstance(response, ObservedResponse) else response.body_preview
    if body is None:
        return ""
    if isinstance(body, str):
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            text = body
        else:
            text = json.dumps(redact_body(decoded), ensure_ascii=False, sort_keys=True)
    else:
        text = json.dumps(redact_body(body), ensure_ascii=False, sort_keys=True)
    return redact_text(text)[:500]


def _evidence_prefix(request: RequestSpec) -> list[str]:
    return [f"Request: {request.method} {redact_url(request.url)}"]


def _diagnosis(
    *,
    severity: Severity,
    title: str,
    summary: str,
    confidence: float,
    likely_cause: str,
    evidence: list[str],
    fix_steps: list[str],
    category: str,
) -> Diagnosis:
    return Diagnosis(
        severity=severity,
        title=title,
        summary=summary,
        confidence=confidence,
        likely_cause=likely_cause,
        evidence=evidence,
        fix_steps=fix_steps,
        category=category,
        source="rules",
    )


def analyze_request(
    request: RequestSpec,
    observed: ResponseEvidence | None = None,
) -> Diagnosis:
    """Return the highest-signal diagnosis supported by available evidence."""

    evidence = _evidence_prefix(request)
    error = (observed.error or "") if observed is not None else ""
    status = observed.status_code if observed is not None else None
    response_headers = observed.headers if observed is not None else {}
    body_text = _body_text(observed)
    body_lower = body_text.casefold()

    if error:
        safe_error = redact_text(error)[:500]
        evidence.append(f"Transport error: {safe_error}")
        error_lower = error.casefold()
        if "timeout" in error_lower or "timed out" in error_lower:
            return _diagnosis(
                severity=Severity.HIGH,
                title="Request timed out",
                summary="The request did not receive a response within the configured deadline.",
                confidence=0.97,
                likely_cause="The upstream is slow or unreachable, or the client timeout is too short.",
                evidence=evidence,
                fix_steps=[
                    "Check upstream health and network reachability.",
                    "Retry with bounded exponential backoff only for idempotent requests.",
                    "Increase the timeout only after measuring normal endpoint latency.",
                ],
                category="timeout",
            )
        if any(term in error_lower for term in ("name or service", "dns", "nodename", "resolve")):
            return _diagnosis(
                severity=Severity.HIGH,
                title="Hostname resolution failed",
                summary="DNS could not resolve the API hostname.",
                confidence=0.97,
                likely_cause="The hostname is misspelled, unavailable in this network, or its DNS record is missing.",
                evidence=evidence,
                fix_steps=[
                    "Verify the hostname and environment-specific base URL.",
                    "Check DNS resolution from the same runtime environment.",
                    "Confirm VPN or private-network requirements.",
                ],
                category="dns",
            )
        if any(term in error_lower for term in ("certificate", "ssl", "tls")):
            return _diagnosis(
                severity=Severity.HIGH,
                title="TLS validation failed",
                summary="A secure connection could not be established because certificate validation failed.",
                confidence=0.96,
                likely_cause="The certificate is expired, untrusted, or does not match the hostname.",
                evidence=evidence,
                fix_steps=[
                    "Inspect the server certificate chain and hostname coverage.",
                    "Update the runtime trust store if the issuer is valid.",
                    "Do not disable TLS verification as a production fix.",
                ],
                category="tls",
            )
        if "refused" in error_lower or "connect" in error_lower:
            return _diagnosis(
                severity=Severity.HIGH,
                title="Connection failed",
                summary="The client could not establish a connection to the API endpoint.",
                confidence=0.9,
                likely_cause="The service is down, the port is closed, or a firewall is blocking access.",
                evidence=evidence,
                fix_steps=[
                    "Confirm that the service and port are available.",
                    "Check firewall, proxy, and network routing rules.",
                    "Verify that the URL uses the correct scheme and port.",
                ],
                category="connectivity",
            )
        return _diagnosis(
            severity=Severity.HIGH,
            title="HTTP transport failed",
            summary="The request failed before a usable HTTP response was received.",
            confidence=0.78,
            likely_cause="A network, protocol, or client transport error interrupted the request.",
            evidence=evidence,
            fix_steps=[
                "Inspect the complete client exception and network path.",
                "Retry only if the operation is safe.",
            ],
            category="transport",
        )

    if status is not None:
        evidence.append(f"Observed HTTP status: {status}")
        if body_text:
            evidence.append(f"Response preview: {body_text}")

    if status == 401:
        auth = _header(request.headers, "Authorization")
        if auth is None:
            evidence.append("The request has no Authorization header.")
        else:
            evidence.append("An Authorization header was present (value redacted).")
        return _diagnosis(
            severity=Severity.HIGH,
            title="Authentication was rejected",
            summary="The server returned 401 Unauthorized, so it did not accept the supplied identity.",
            confidence=0.98,
            likely_cause="The credential is missing, expired, malformed, or intended for another environment.",
            evidence=evidence,
            fix_steps=[
                "Provide a current credential through a secret manager or environment variable.",
                "Confirm the required authorization scheme, commonly 'Bearer <token>'.",
                "Verify the token audience, issuer, and expiry without logging the token.",
            ],
            category="authentication",
        )

    if status == 403:
        return _diagnosis(
            severity=Severity.HIGH,
            title="Request is not permitted",
            summary="The server authenticated the request but refused access to this operation.",
            confidence=0.96,
            likely_cause="The identity lacks a required role, scope, tenant membership, or policy grant.",
            evidence=evidence,
            fix_steps=[
                "Compare the credential's scopes and roles with the endpoint requirements.",
                "Check tenant, resource ownership, and IP allow-list policies.",
                "Request the minimum additional permission needed.",
            ],
            category="authorization",
        )

    if status == 404:
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="Endpoint or resource was not found",
            summary="The server returned 404 for the requested path.",
            confidence=0.94,
            likely_cause="The base URL, API version, route, or resource identifier is incorrect for this environment.",
            evidence=evidence,
            fix_steps=[
                "Compare the URL with the provider's current API documentation.",
                "Verify the API version and environment-specific base URL.",
                "Confirm that the resource identifier exists and is visible to this identity.",
            ],
            category="endpoint",
        )

    if status == 405:
        allow = _header(response_headers, "Allow")
        if allow:
            evidence.append(f"Server Allow header: {redact_text(allow)}")
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="HTTP method is not allowed",
            summary=f"The endpoint rejected the {request.method} method.",
            confidence=0.98,
            likely_cause="The route exists but expects a different HTTP method.",
            evidence=evidence,
            fix_steps=[
                f"Use one of the methods advertised by the server{f': {allow}' if allow else ''}.",
                "Confirm that the intended operation and endpoint path match.",
            ],
            category="method",
        )

    if status in {408, 504}:
        return _diagnosis(
            severity=Severity.HIGH,
            title="Upstream request timed out",
            summary=f"HTTP {status} indicates the server or gateway exceeded its request deadline.",
            confidence=0.97,
            likely_cause="An upstream dependency is slow, overloaded, or unavailable.",
            evidence=evidence,
            fix_steps=[
                "Check upstream latency and saturation metrics.",
                "Reduce request work or move long-running operations to an asynchronous job.",
                "Use bounded retries only where the operation is idempotent.",
            ],
            category="timeout",
        )

    if status == 409:
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="Request conflicts with current state",
            summary="The server returned 409 Conflict.",
            confidence=0.94,
            likely_cause="The resource version, uniqueness constraint, or idempotency state conflicts with the request.",
            evidence=evidence,
            fix_steps=[
                "Read the latest resource state before retrying.",
                "Check uniqueness and idempotency-key requirements.",
                "Apply optimistic-concurrency headers when the API supports them.",
            ],
            category="conflict",
        )

    if status == 413:
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="Request payload is too large",
            summary="The server rejected the request body size.",
            confidence=0.99,
            likely_cause="The payload exceeds the endpoint or gateway limit.",
            evidence=evidence,
            fix_steps=[
                "Reduce or paginate the payload.",
                "Use the API's upload workflow for large content.",
            ],
            category="payload-size",
        )

    if status == 415:
        content_type = _header(request.headers, "Content-Type")
        evidence.append(f"Request Content-Type: {content_type or 'missing'}")
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="Unsupported request media type",
            summary="The endpoint rejected the request body's Content-Type.",
            confidence=0.99,
            likely_cause="Content-Type is missing or does not match the payload encoding expected by the endpoint.",
            evidence=evidence,
            fix_steps=[
                "Set Content-Type to the media type required by the endpoint.",
                "Serialize the body consistently with that media type.",
            ],
            category="content-type",
        )

    if status == 422:
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="Payload validation failed",
            summary="The endpoint understood the payload format but rejected one or more values.",
            confidence=0.98,
            likely_cause="A required field is absent, has the wrong type, or violates a domain constraint.",
            evidence=evidence,
            fix_steps=[
                "Use the response's field-level errors to update the payload.",
                "Validate required fields and types against the current API schema.",
                "Add a regression test for the corrected payload.",
            ],
            category="validation",
        )

    if status == 429:
        retry_after = _header(response_headers, "Retry-After")
        if retry_after:
            evidence.append(f"Retry-After: {redact_text(retry_after)}")
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="API rate limit exceeded",
            summary="The server returned 429 Too Many Requests.",
            confidence=0.99,
            likely_cause="The client exceeded a request, token, or concurrency quota.",
            evidence=evidence,
            fix_steps=[
                "Honor Retry-After and use exponential backoff with jitter.",
                "Reduce concurrency or cache repeated reads.",
                "Track quota headers and request a higher limit only if necessary.",
            ],
            category="rate-limit",
        )

    if status is not None and status >= 500:
        return _diagnosis(
            severity=Severity.HIGH,
            title="Server-side failure",
            summary=f"The API returned HTTP {status}, indicating a server or upstream failure.",
            confidence=0.95,
            likely_cause="The service or one of its dependencies failed while handling a valid HTTP request.",
            evidence=evidence,
            fix_steps=[
                "Capture the provider request/correlation ID from response headers.",
                "Check the service status and server logs.",
                "Retry idempotent operations with bounded backoff; avoid blind retries for writes.",
            ],
            category="server",
        )

    if status == 400:
        if any(term in body_lower for term in ("json", "parse", "malformed", "syntax")):
            likely_cause = (
                "The payload is malformed or its encoding does not match the declared media type."
            )
            steps = [
                "Validate the serialized JSON or form payload locally.",
                "Ensure Content-Type matches the payload encoding.",
                "Compare field names and nesting with the API schema.",
            ]
        else:
            likely_cause = (
                "The request syntax, parameters, or payload do not satisfy the endpoint contract."
            )
            steps = [
                "Inspect the response error details for a parameter or field name.",
                "Compare query parameters, headers, and body with the current API schema.",
                "Reduce the request to the smallest valid example, then add fields back.",
            ]
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="Request was rejected as invalid",
            summary="The server returned 400 Bad Request.",
            confidence=0.9,
            likely_cause=likely_cause,
            evidence=evidence,
            fix_steps=steps,
            category="bad-request",
        )

    if status is not None and status >= 400:
        return _diagnosis(
            severity=Severity.MEDIUM,
            title=f"HTTP {status} request failure",
            summary="The server returned a client-error response.",
            confidence=0.82,
            likely_cause="The request conflicts with an endpoint-specific requirement.",
            evidence=evidence,
            fix_steps=["Inspect the response body and API documentation for this status code."],
            category="client-error",
        )

    if status is not None and 300 <= status < 400:
        location = _header(response_headers, "Location")
        if location:
            evidence.append(f"Redirect Location: {redact_url(location)}")
        return _diagnosis(
            severity=Severity.LOW,
            title="Request returned a redirect",
            summary=f"The endpoint returned HTTP {status} instead of a final API response.",
            confidence=0.92,
            likely_cause="The base URL or route moved, or the endpoint enforces another scheme or host.",
            evidence=evidence,
            fix_steps=[
                "Update the configured endpoint to the documented canonical URL.",
                "Validate redirect targets before following them.",
            ],
            category="redirect",
        )

    if status is not None and 200 <= status < 300:
        return _diagnosis(
            severity=Severity.INFO,
            title="Request succeeded",
            summary=f"The available evidence shows a successful HTTP {status} response.",
            confidence=0.99,
            likely_cause="No HTTP-layer failure was reproduced.",
            evidence=evidence,
            fix_steps=[
                "If application data is still wrong, verify the response schema and business assertions."
            ],
            category="success",
        )

    content_type = _header(request.headers, "Content-Type")
    if request.body is not None and request.method in {"GET", "HEAD"}:
        evidence.append(f"A request body is attached to {request.method}.")
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="Body attached to a retrieval request",
            summary=f"Some servers and intermediaries ignore or reject bodies on {request.method} requests.",
            confidence=0.78,
            likely_cause="Parameters intended for the query string or a write endpoint were placed in the request body.",
            evidence=evidence,
            fix_steps=[
                "Move supported parameters to the query string.",
                "Use the documented write method if a body is required.",
            ],
            category="request-shape",
        )

    if isinstance(request.body, (dict, list)) and content_type is None:
        evidence.append("A JSON-shaped body is present without Content-Type.")
        return _diagnosis(
            severity=Severity.MEDIUM,
            title="JSON media type is missing",
            summary="The request contains JSON-shaped data but does not declare its encoding.",
            confidence=0.82,
            likely_cause="The server may parse the body using the wrong decoder or reject it as unsupported.",
            evidence=evidence,
            fix_steps=[
                "Set Content-Type: application/json.",
                "Serialize the payload as valid JSON.",
            ],
            category="content-type",
        )

    return _diagnosis(
        severity=Severity.LOW,
        title="More response evidence is needed",
        summary="The request is syntactically plausible, but no failure response or transport error was supplied.",
        confidence=0.35,
        likely_cause="The failure cannot be isolated from request data alone.",
        evidence=evidence,
        fix_steps=[
            "Add the observed status code, safe response excerpt, or client error.",
            "Run the optional safe probe only for a public endpoint you are authorised to call.",
        ],
        category="insufficient-evidence",
    )


def suggest_correction(
    request: RequestSpec,
    diagnosis: Diagnosis,
    observed: ResponseEvidence | None = None,
) -> RequestSpec:
    """Apply only corrections directly supported by evidence."""

    headers = dict(request.headers)
    method = request.method

    # Remove values that clients should recalculate after any body/header edit.
    headers = {
        key: value
        for key, value in headers.items()
        if key.casefold() not in {"content-length", "host", "connection"}
    }

    if diagnosis.category == "content-type" and isinstance(request.body, (dict, list)):
        if _header(headers, "Content-Type") is None:
            headers["Content-Type"] = "application/json"

    if diagnosis.category == "authentication":
        auth_key = next((key for key in headers if key.casefold() == "authorization"), None)
        if auth_key and " " not in headers[auth_key].strip():
            headers[auth_key] = f"Bearer {headers[auth_key].strip()}"

    if diagnosis.category == "method" and observed is not None:
        allow = _header(observed.headers, "Allow")
        if allow:
            candidates = [item.strip().upper() for item in allow.split(",") if item.strip()]
            if candidates:
                method = candidates[0]

    return RequestSpec(method=method, url=request.url, headers=headers, body=request.body)


__all__ = ["RULES_VERSION", "ResponseEvidence", "analyze_request", "suggest_correction"]

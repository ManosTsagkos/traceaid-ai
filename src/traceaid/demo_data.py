"""Built-in, credential-free incidents used by the API and web demo."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_EXAMPLES: tuple[dict[str, Any], ...] = (
    {
        "id": "expired-token",
        "name": "Expired bearer token",
        "description": "A protected endpoint rejects an expired access token.",
        "category": "Authentication",
        "request": {
            "method": "GET",
            "url": "https://api.example.com/v1/projects",
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer demo-expired-token",
            },
            "body": None,
        },
        "observed": {
            "status_code": 401,
            "headers": {
                "content-type": "application/json",
                "www-authenticate": 'Bearer error="invalid_token"',
            },
            "body": {
                "error": "invalid_token",
                "message": "The access token expired",
            },
            "latency_ms": 184,
            "error": None,
        },
        "execute_probe": False,
        "use_ai": False,
    },
    {
        "id": "validation-error",
        "name": "Payload validation failure",
        "description": "A JSON payload has the wrong types and a missing field.",
        "category": "Validation",
        "request": {
            "method": "POST",
            "url": "https://api.example.com/v1/users",
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-Key": "demo-secret-key",
            },
            "body": {"email": "not-an-email", "age": "twenty eight"},
        },
        "observed": {
            "status_code": 422,
            "headers": {"content-type": "application/json"},
            "body": {
                "detail": [
                    {
                        "loc": ["body", "email"],
                        "msg": "value is not a valid email",
                        "type": "value_error.email",
                    },
                    {
                        "loc": ["body", "name"],
                        "msg": "field required",
                        "type": "missing",
                    },
                ]
            },
            "latency_ms": 96,
            "error": None,
        },
        "execute_probe": False,
        "use_ai": False,
    },
    {
        "id": "rate-limit",
        "name": "Rate limit exceeded",
        "description": "A third-party API throttles a burst and returns retry guidance.",
        "category": "Resilience",
        "request": {
            "method": "GET",
            "url": "https://api.example.com/v1/search?q=observability",
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "demo-secret-key",
            },
            "body": None,
        },
        "observed": {
            "status_code": 429,
            "headers": {
                "content-type": "application/json",
                "retry-after": "30",
                "x-ratelimit-remaining": "0",
            },
            "body": {
                "error": "rate_limit_exceeded",
                "message": "Retry after 30 seconds",
            },
            "latency_ms": 71,
            "error": None,
        },
        "execute_probe": False,
        "use_ai": False,
    },
    {
        "id": "missing-content-type",
        "name": "Missing JSON content type",
        "description": "An otherwise valid JSON request uses the wrong media type.",
        "category": "Content negotiation",
        "request": {
            "method": "POST",
            "url": "https://api.example.com/v1/orders",
            "headers": {"Accept": "application/json"},
            "body": {"product_id": "sku_123", "quantity": 1},
        },
        "observed": {
            "status_code": 415,
            "headers": {"content-type": "application/json"},
            "body": {"error": "unsupported_media_type", "expected": "application/json"},
            "latency_ms": 58,
        },
        "execute_probe": False,
        "use_ai": False,
    },
    {
        "id": "wrong-method",
        "name": "Wrong HTTP method",
        "description": "A read-only endpoint rejects POST and declares the supported method.",
        "category": "Request contract",
        "request": {
            "method": "POST",
            "url": "https://api.example.com/v1/status",
            "headers": {"Accept": "application/json"},
            "body": None,
        },
        "observed": {
            "status_code": 405,
            "headers": {"allow": "GET", "content-type": "application/json"},
            "body": {"error": "method_not_allowed"},
            "latency_ms": 41,
        },
        "execute_probe": False,
        "use_ai": False,
    },
    {
        "id": "upstream-timeout",
        "name": "Upstream request timeout",
        "description": "A slow read reaches the client timeout before a response arrives.",
        "category": "Connectivity",
        "request": {
            "method": "GET",
            "url": "https://api.example.com/v1/reports/daily",
            "headers": {"Accept": "application/json"},
            "body": None,
        },
        "observed": {"error": "ReadTimeout: upstream did not respond", "latency_ms": 8000},
        "execute_probe": False,
        "use_ai": False,
    },
)


def list_examples() -> list[dict[str, Any]]:
    """Return independent example payloads safe for callers to mutate."""

    return deepcopy(list(_EXAMPLES))


def get_example(example_id: str) -> dict[str, Any] | None:
    """Find a built-in incident by its stable identifier."""

    for example in _EXAMPLES:
        if example["id"] == example_id:
            return deepcopy(example)
    return None

# API reference

TraceAid exposes a versioned JSON API under `/api/v1`. FastAPI generates the authoritative OpenAPI document at `/api/openapi.json` and interactive documentation at `/docs`.

Unless otherwise noted, requests and responses use `application/json`. Timestamps use UTC ISO 8601 format.

## Data model

### `RequestSpec`

Describes the request that failed or should be safely probed.

| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `method` | string | no | `GET` | Normalized HTTP method. |
| `url` | string | yes | — | Absolute `http` or `https` URL. Live probes apply additional SSRF checks. |
| `headers` | object of strings | no | `{}` | Sensitive names and values are redacted in output. |
| `body` | any JSON value or string | no | `null` | Original request body. |

### `ObservedResponse`

Captures what the caller already observed. At least one of `status_code` or `error` is required.

| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `status_code` | integer or `null` | conditional | `null` | HTTP response status. |
| `headers` | object of strings | no | `{}` | Response headers relevant to diagnosis. |
| `body` | any JSON value or string | no | `null` | Error payload or response excerpt. |
| `latency_ms` | number or `null` | no | `null` | Observed end-to-end latency. |
| `error` | string or `null` | conditional | `null` | Network/client error when no status was received. |

### `IncidentRequest`

The input accepted by the diagnosis endpoint.

| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `request` | `RequestSpec` | yes | — | The failed request. |
| `observed` | `ObservedResponse` or `null` | no | `null` | Existing response evidence. |
| `execute_probe` | boolean | no | `false` | Ask the server to replay the request. Requires server-side live probes to be enabled. |
| `use_ai` | boolean | no | `false` | Request optional AI enrichment. Requires `OPENAI_API_KEY`. |
| `context` | string or `null` | no | `null` | Short, non-secret debugging context. |

`AnalyzeRequest` is retained as a model alias for clients using analysis terminology.

## Endpoints

### `GET /api/health`

Returns a configuration-safe health response. It does not reveal credentials.

```bash
curl http://localhost:8000/api/health
```

Use this endpoint for local checks and container readiness. A successful response uses HTTP `200`.

### `GET /api/v1/meta`

Returns the running version, default mode, and a non-sensitive list of supported capabilities. It is useful for clients and deployment smoke tests.

### `GET /api/v1/examples`

Returns synthetic incidents for the browser demo and API clients. Examples contain no real tokens. Each item combines display metadata with a `payload` object; submit that nested `payload` to `/api/v1/diagnose`.

```bash
curl http://localhost:8000/api/v1/examples
```

Abbreviated response shape:

```json
[
  {
    "id": "expired-token",
    "name": "Expired bearer token",
    "description": "A protected endpoint rejects an expired access token.",
    "category": "Authentication",
    "payload": {
      "request": {"method": "GET", "url": "https://api.example.com/v1/projects"},
      "observed": {"status_code": 401}
    }
  }
]
```

### `POST /api/v1/examples/{example_id}/diagnose`

Runs one built-in example by ID through the same service used by `/api/v1/diagnose`. This is convenient for demos and smoke tests because the server supplies the credential-free payload. Unknown IDs return `404`.

### `POST /api/v1/parse-curl`

Parses a command into a `RequestSpec` without executing it.

Request:

```json
{
  "command": "curl -X POST 'https://api.example.com/v1/orders' -H 'Content-Type: application/json' -d '{\"product_id\":\"sku_123\"}'"
}
```

Response:

```json
{
  "method": "POST",
  "url": "https://api.example.com/v1/orders",
  "headers": {
    "Content-Type": "application/json"
  },
  "body": {
    "product_id": "sku_123"
  }
}
```

The parser supports common `curl` forms for method, headers, and body data. It does not run shell expansion, read local files, or execute the command.

### `POST /api/v1/diagnose`

Runs validation, redaction, deterministic rules, optional safe probing, optional AI enrichment, and artifact generation.

Request:

```json
{
  "request": {
    "method": "POST",
    "url": "https://api.example.com/v1/orders",
    "headers": {
      "Authorization": "Bearer demo-secret",
      "Content-Type": "application/json"
    },
    "body": {
      "product_id": "sku_123",
      "quantity": 1
    }
  },
  "observed": {
    "status_code": 401,
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "error": "invalid_token"
    },
    "latency_ms": 183
  },
  "execute_probe": false,
  "use_ai": false,
  "context": "Synthetic checkout integration example"
}
```

Response shape:

```json
{
  "id": "diagnosis-id",
  "created_at": "2026-10-02T09:30:00Z",
  "mode": "rules",
  "redacted_request": {
    "method": "POST",
    "url": "https://api.example.com/v1/orders",
    "headers": {
      "Authorization": "<redacted>",
      "Content-Type": "application/json"
    },
    "body": {
      "product_id": "sku_123",
      "quantity": 1
    }
  },
  "diagnosis": {
    "severity": "high",
    "title": "Authentication failed",
    "summary": "The API rejected the supplied credentials.",
    "confidence": 0.96,
    "likely_cause": "The bearer token is missing, expired, malformed, or invalid for this API.",
    "evidence": ["The observed status code is 401."],
    "fix_steps": ["Issue a valid token and send it with the Bearer authorization scheme."],
    "category": "authentication",
    "source": "rules"
  },
  "artifacts": {
    "corrected_curl": "curl ...",
    "python_snippet": "import httpx\n...",
    "pytest_test": "def test_create_order():\n    ...",
    "markdown_report": "# TraceAid diagnosis\n..."
  },
  "probe": null,
  "metadata": {
    "rules_version": "1.0",
    "llm_provider": null,
    "probe_requested": false,
    "probe_performed": false,
    "warnings": []
  }
}
```

`mode` records the path actually used (for example, deterministic rules or hybrid enrichment). Provider failure does not discard deterministic findings. `AnalysisReport` is an alias of the same response model.

## Validation and error behavior

TraceAid uses standard FastAPI error bodies:

```json
{
  "detail": "Human-readable error or structured validation details"
}
```

Typical status codes:

| Status | Meaning |
| --- | --- |
| `200` | Request parsed or diagnosis completed. |
| `404` | A requested built-in example ID does not exist. |
| `422` | JSON does not satisfy the Pydantic contract, or a `curl` command cannot be safely parsed. |
| `502` | An explicitly requested external operation failed without a usable fallback. Normal AI/provider failures use the deterministic fallback instead. |
| `500` | Unexpected internal failure. The response should not echo secrets. |

Exact validation details are also visible in `/docs`.

## Live probe behavior

Submitting `execute_probe: true` does not override server configuration. The server must also have `TRACEAID_ENABLE_LIVE_PROBES=true`. If probing is disabled or the target fails policy, diagnosis still succeeds: `probe.attempted` is `false` and `metadata.warnings` explains the safe refusal. Before an allowed outbound request, TraceAid validates the URL and resolved destination, applies time and response-size bounds, does not follow redirects, and redacts retained evidence.

For internet-facing deployments, also enforce network-level egress restrictions. Application checks alone are not a complete SSRF boundary.

## AI behavior

Submitting `use_ai: true` requests enrichment; it does not guarantee that a provider call will be made. If no key is configured, the provider is unavailable, or the structured response fails validation, TraceAid returns deterministic analysis and exposes a non-sensitive mode/metadata indication. No caller-supplied API key should be placed in the JSON request.

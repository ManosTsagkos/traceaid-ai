"""End-to-end API contract tests using the credential-free rules pipeline."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from traceaid.main import create_app

client = TestClient(create_app())


def test_health_and_metadata() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.headers["x-request-id"]
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["content-security-policy"].startswith("default-src 'self'")

    metadata = client.get("/api/v1/meta")
    assert metadata.status_code == 200
    assert "secret-redaction" in metadata.json()["capabilities"]


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
@pytest.mark.parametrize(
    ("root_path", "mount_path", "request_prefix"),
    [
        ("", "", ""),
        ("", "/traceaid", "/traceaid"),
        ("/traceaid", "", "/traceaid"),
        ("/traceaid", "", ""),
        ("/gateway", "/traceaid", "/gateway/traceaid"),
    ],
    ids=["standalone", "mounted", "proxy-prefix", "proxy-stripped", "proxy-and-mount"],
)
def test_api_documentation_allows_its_assets_without_weakening_application_csp(
    path: str, root_path: str, mount_path: str, request_prefix: str
) -> None:
    application = create_app()
    if mount_path:
        parent = FastAPI()
        parent.mount(mount_path, application)
        application = parent
    documentation_client = TestClient(application, root_path=root_path)
    public_path = f"{request_prefix}{path}"
    response = documentation_client.get(public_path)
    assert response.status_code == 200
    assert "https://cdn.jsdelivr.net" in response.text
    openapi_path = f"{root_path}{mount_path}/api/openapi.json"
    assert openapi_path in response.text
    schema_response = documentation_client.get(openapi_path)
    assert schema_response.status_code == 200
    assert "/api/v1/diagnose" in schema_response.json()["paths"]
    policy = response.headers["content-security-policy"]
    script_policy = next(
        item for item in policy.split(";") if item.strip().startswith("script-src")
    )
    assert "https://cdn.jsdelivr.net" in script_policy
    assert "'unsafe-inline'" not in script_policy
    if path == "/docs":
        nonce = re.search(r'<script nonce="([^"]+)">', response.text)
        assert nonce is not None
        assert f"'nonce-{nonce.group(1)}'" in script_policy
        assert documentation_client.get(public_path).headers["content-security-policy"] != policy
    assert "fonts.googleapis.com" not in response.text
    for application_path in ("/", "/api/health", "/api/openapi.json"):
        application_response = documentation_client.get(f"{request_prefix}{application_path}")
        assert application_response.status_code == 200
        strict_policy = application_response.headers["content-security-policy"]
        assert "cdn.jsdelivr.net" not in strict_policy
        assert "'unsafe-inline'" not in strict_policy
    for lookalike_path in ("/docs-extra", "/docs/other", "/redoc-extra"):
        missing = documentation_client.get(f"{request_prefix}{lookalike_path}")
        assert missing.status_code == 404
        assert "cdn.jsdelivr.net" not in missing.headers["content-security-policy"]


def test_examples_can_run_through_real_pipeline() -> None:
    examples = client.get("/api/v1/examples")
    assert examples.status_code == 200
    assert len(examples.json()) >= 3

    report = client.post("/api/v1/examples/validation-error/diagnose")
    assert report.status_code == 200, report.text
    payload = report.json()
    assert payload["diagnosis"]["severity"] in {"low", "medium", "high", "critical"}
    assert payload["diagnosis"]["confidence"] > 0.5
    assert payload["artifacts"]["pytest_test"]
    assert "demo-secret-key" not in report.text


def test_diagnose_redacts_authorization_from_every_artifact() -> None:
    response = client.post(
        "/api/v1/diagnose",
        json={
            "request": {
                "method": "GET",
                "url": "https://api.example.com/v1/projects",
                "headers": {"Authorization": "Bearer top-secret-token"},
            },
            "observed": {
                "status_code": 401,
                "headers": {"www-authenticate": 'Bearer error="invalid_token"'},
                "body": {"error": "invalid_token"},
            },
        },
    )
    assert response.status_code == 200, response.text
    assert "top-secret-token" not in response.text
    assert response.json()["diagnosis"]["category"] == "authentication"


def test_parse_curl_preserves_json_types() -> None:
    response = client.post(
        "/api/v1/parse-curl",
        json={
            "command": (
                "curl -X POST https://api.example.com/v1/users "
                "-H 'Content-Type: application/json' "
                '-d \'{"enabled":true,"attempts":3}\''
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["method"] == "POST"
    assert response.json()["body"] == {"enabled": True, "attempts": 3}


def test_unknown_example_is_a_clear_404() -> None:
    response = client.post("/api/v1/examples/not-real/diagnose")
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown example"

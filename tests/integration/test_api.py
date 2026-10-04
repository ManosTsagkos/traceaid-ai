"""End-to-end API contract tests using the credential-free rules pipeline."""

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

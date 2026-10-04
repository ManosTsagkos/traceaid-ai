import json

import pytest
from pydantic import ValidationError

from traceaid.config import Settings
from traceaid.models import IncidentRequest, ObservedResponse, RequestSpec

pytestmark = pytest.mark.unit


def test_public_models_dump_to_plain_json() -> None:
    incident = IncidentRequest(
        request=RequestSpec(
            method="post",
            url="https://api.example.com/widgets",
            headers={"Content-Type": "application/json"},
            body={"name": "demo"},
        ),
        observed=ObservedResponse(status_code=422, body={"field": "name"}),
    )

    dumped = incident.model_dump()

    assert dumped["request"]["method"] == "POST"
    assert json.loads(json.dumps(dumped))["observed"]["status_code"] == 422


def test_request_spec_rejects_non_http_and_header_injection() -> None:
    with pytest.raises(ValidationError):
        RequestSpec(method="GET", url="file:///etc/passwd")

    with pytest.raises(ValidationError):
        RequestSpec(
            method="GET", url="https://example.com", headers={"X-Test": "ok\r\nInjected: yes"}
        )


def test_observed_response_requires_status_or_error() -> None:
    with pytest.raises(ValidationError):
        ObservedResponse(body="nothing useful")


def test_settings_from_explicit_mapping() -> None:
    settings = Settings.from_env(
        {
            "OPENAI_MODEL": "gpt-test",
            "TRACEAID_ENABLE_LIVE_PROBES": "yes",
            "TRACEAID_REQUEST_TIMEOUT_SECONDS": "2.5",
            "TRACEAID_MAX_RESPONSE_BYTES": "4096",
            "TRACEAID_ALLOWED_ORIGINS": "https://one.example, https://two.example",
            "TRACEAID_LOG_LEVEL": "debug",
        }
    )

    assert settings.openai_model == "gpt-test"
    assert settings.enable_live_probes is True
    assert settings.request_timeout_seconds == 2.5
    assert settings.allowed_origins == ["https://one.example", "https://two.example"]
    assert settings.log_level == "DEBUG"


def test_settings_rejects_ambiguous_boolean() -> None:
    with pytest.raises(ValueError, match="TRACEAID_ENABLE_LIVE_PROBES"):
        Settings.from_env({"TRACEAID_ENABLE_LIVE_PROBES": "sometimes"})

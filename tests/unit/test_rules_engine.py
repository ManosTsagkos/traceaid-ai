import pytest

from traceaid.models import ObservedResponse, RequestSpec
from traceaid.services.rules_engine import analyze_request, suggest_correction

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "authentication"),
        (403, "authorization"),
        (404, "endpoint"),
        (405, "method"),
        (415, "content-type"),
        (422, "validation"),
        (429, "rate-limit"),
        (503, "server"),
    ],
)
def test_status_rules_are_deterministic(status: int, category: str) -> None:
    request = RequestSpec(method="POST", url="https://api.example.com/items", body={"name": "Ada"})
    observed = ObservedResponse(status_code=status, body={"error": "failed"})

    first = analyze_request(request, observed)
    second = analyze_request(request, observed)

    assert first == second
    assert first.category == category
    assert first.evidence


def test_transport_error_rules() -> None:
    request = RequestSpec(method="GET", url="https://api.example.com")

    diagnosis = analyze_request(request, ObservedResponse(error="DNS name could not resolve"))

    assert diagnosis.category == "dns"
    assert diagnosis.confidence > 0.9


def test_static_rule_detects_json_without_content_type() -> None:
    request = RequestSpec(method="POST", url="https://api.example.com/items", body={"name": "Ada"})

    diagnosis = analyze_request(request)
    corrected = suggest_correction(request, diagnosis)

    assert diagnosis.category == "content-type"
    assert corrected.headers["Content-Type"] == "application/json"


def test_405_correction_uses_allow_header() -> None:
    request = RequestSpec(method="POST", url="https://api.example.com/items")
    observed = ObservedResponse(status_code=405, headers={"Allow": "GET, HEAD"})
    diagnosis = analyze_request(request, observed)

    corrected = suggest_correction(request, diagnosis, observed)

    assert corrected.method == "GET"


def test_success_is_not_reported_as_failure() -> None:
    request = RequestSpec(method="GET", url="https://api.example.com/health")
    diagnosis = analyze_request(request, ObservedResponse(status_code=204))

    assert diagnosis.category == "success"
    assert diagnosis.severity.value == "info"

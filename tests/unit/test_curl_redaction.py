import pytest

from traceaid.models import RequestSpec
from traceaid.services.curl_parser import CurlParseError, parse_curl
from traceaid.services.redaction import REDACTED, redact_body, redact_request, redact_text

pytestmark = pytest.mark.unit


def test_parse_browser_style_json_curl() -> None:
    request = parse_curl(
        "curl 'https://api.example.com/v1/items' "
        "-H 'Authorization: Bearer top-secret' "
        '--json \'{"name":"Ada","active":true}\''
    )

    assert request.method == "POST"
    assert request.body == {"name": "Ada", "active": True}
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Accept"] == "application/json"


def test_parse_get_moves_data_to_query() -> None:
    request = parse_curl("curl -G https://api.example.com/search -d 'q=hello world' -d limit=3")

    assert request.method == "GET"
    assert request.body is None
    assert "q=hello+world" in request.url
    assert "limit=3" in request.url


def test_parse_basic_auth_and_explicit_method() -> None:
    request = parse_curl("curl -XDELETE -u alice:secret https://api.example.com/items/1")

    assert request.method == "DELETE"
    assert request.headers["Authorization"].startswith("Basic ")


@pytest.mark.parametrize(
    "command",
    [
        "wget https://example.com",
        "curl --data @secrets.json https://example.com",
        "curl --unsupported value https://example.com",
        "curl https://one.example https://two.example",
    ],
)
def test_parse_curl_fails_closed(command: str) -> None:
    with pytest.raises(CurlParseError):
        parse_curl(command)


def test_redaction_covers_headers_url_and_nested_json() -> None:
    original = RequestSpec(
        method="POST",
        url="https://alice:secret@example.com/items?api_key=url-secret&view=short",
        headers={"Authorization": "Bearer header-secret", "X-Trace": "safe"},
        body={"profile": {"password": "body-secret"}, "items": [{"access_token": "token"}]},
    )

    safe = redact_request(original)
    serialised = safe.model_dump_json()

    assert "secret" not in serialised
    assert safe.headers["Authorization"] == REDACTED
    assert safe.headers["X-Trace"] == "safe"
    assert safe.body == {
        "profile": {"password": REDACTED},
        "items": [{"access_token": REDACTED}],
    }


def test_text_and_body_redaction_preserve_non_secrets() -> None:
    assert redact_text("Authorization=Bearer abcdefghi") != "Authorization=Bearer abcdefghi"
    assert redact_body({"monkey": "banana", "client_secret": "hidden"}) == {
        "monkey": "banana",
        "client_secret": REDACTED,
    }

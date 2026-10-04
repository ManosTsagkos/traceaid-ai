import httpx
import pytest

from traceaid.config import Settings
from traceaid.models import RequestSpec
from traceaid.services.probe import ProbeClient
from traceaid.services.url_security import UnsafeTargetError, ValidatedTarget, validate_public_url

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_url_validation_rejects_private_literal() -> None:
    with pytest.raises(UnsafeTargetError, match="non-public"):
        await validate_public_url("http://127.0.0.1/admin")


@pytest.mark.asyncio
async def test_url_validation_rejects_mixed_dns_answers() -> None:
    async def resolver(hostname: str, port: int) -> list[str]:
        assert hostname == "api.example.com"
        assert port == 443
        return ["93.184.216.34", "10.0.0.5"]

    with pytest.raises(UnsafeTargetError, match="non-public"):
        await validate_public_url("https://api.example.com", resolver=resolver)


@pytest.mark.asyncio
async def test_url_validation_accepts_public_dns_answer() -> None:
    async def resolver(hostname: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    result = await validate_public_url("https://api.example.com/v1", resolver=resolver)

    assert result.resolved_ips == ("93.184.216.34",)


@pytest.mark.asyncio
async def test_probe_is_disabled_by_default() -> None:
    client = ProbeClient(Settings())

    result = await client.execute(RequestSpec(method="GET", url="https://api.example.com"))

    assert result.attempted is False
    assert "disabled" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_probe_collects_bounded_redacted_response() -> None:
    async def validator(url: str) -> ValidatedTarget:
        return ValidatedTarget(
            url=url, hostname="api.example.com", port=443, resolved_ips=("93.184.216.34",)
        )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "TraceAid-AI/1.0"
        assert "x-forwarded-for" not in request.headers
        return httpx.Response(
            401,
            headers={
                "Set-Cookie": "session=server-secret",
                "Location": "https://api.example.com/login?token=secret",
            },
            content=b"Bearer response-secret " + (b"x" * 1500),
        )

    settings = Settings(enable_live_probes=True, max_response_bytes=1024)
    client = ProbeClient(
        settings,
        transport=httpx.MockTransport(handler),
        url_validator=validator,
    )
    request = RequestSpec(
        method="GET",
        url="https://api.example.com/private",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    result = await client.execute(request)

    assert result.attempted is True
    assert result.status_code == 401
    assert result.truncated is True
    assert "response-secret" not in (result.body_preview or "")
    assert result.headers["set-cookie"] == "<redacted>"
    assert "secret" not in (result.redirect_location or "")

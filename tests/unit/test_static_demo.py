"""The portfolio demo must stay aligned with real, credential-free reports."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from traceaid.config import Settings
from traceaid.demo_data import get_example, list_examples
from traceaid.models import DiagnosisReport, IncidentRequest
from traceaid.services.diagnosis import DiagnosisService
from traceaid.static_demo import build_demo, check_demo, prepare_examples

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_prepared_reports_are_reproducible_and_ignore_runtime_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "private-runtime-key")
    monkeypatch.setenv("TRACEAID_ENABLE_LIVE_PROBES", "true")
    first = await prepare_examples()
    assert first == await prepare_examples()
    assert len(first) == 6
    encoded = json.dumps(first)
    for secret in ("private-runtime-key", "demo-expired-token", "demo-secret-key"):
        assert secret not in encoded
    for example in first:
        report = DiagnosisReport.model_validate(example["report"])
        assert report.mode == "rules"
        assert report.metadata.probe_performed is False
        assert report.metadata.llm_provider is None
        assert example["request"] == report.redacted_request.model_dump()
        assert report.artifacts.markdown_report.startswith("# TraceAid diagnosis")


@pytest.mark.asyncio
async def test_builder_uses_relative_assets_and_detects_stale_output(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "keep.txt").write_text("do not remove", encoding="utf-8")
    await build_demo(output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "do not remove"
    html = (output / "index.html").read_text(encoding="utf-8")
    assert 'data-static-demo="true"' in html
    assert 'href="./styles.css"' in html
    assert 'src="./demo-data.js"' in html
    assert 'src="./app.js"' in html
    assert "/static/" not in html
    assert await check_demo(output)
    (output / "app.js").write_text("stale", encoding="utf-8")
    assert not await check_demo(output)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("example_id", "method"),
    [
        ("expired-token", "GET"),
        ("validation-error", "POST"),
        ("rate-limit", "GET"),
        ("missing-content-type", "POST"),
        ("wrong-method", "GET"),
        ("upstream-timeout", "GET"),
    ],
)
async def test_generated_python_and_regression_tests_execute_with_mock_http(
    example_id: str, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = get_example(example_id)
    assert example is not None
    incident = IncidentRequest.model_validate(
        {key: example[key] for key in ("request", "observed")}
    )
    report = await DiagnosisService(Settings()).diagnose(incident)
    monkeypatch.setenv("TRACEAID_AUTHORIZATION", "Bearer replacement-test-token")
    monkeypatch.setenv("TRACEAID_X_API_KEY", "replacement-test-key")
    with respx.mock(assert_all_called=True, assert_all_mocked=True) as router:
        route = router.route(method=method, url=incident.request.url).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        exec(compile(report.artifacts.python_snippet, "snippet.py", "exec"), {})  # noqa: S102
        namespace: dict[str, object] = {}
        exec(compile(report.artifacts.pytest_test, "regression.py", "exec"), namespace)  # noqa: S102
        test_function = namespace["test_corrected_api_request_regression"]
        assert callable(test_function)
        test_function()
        assert route.call_count == 2
        if example_id == "missing-content-type":
            assert route.calls[0].request.headers["Content-Type"] == "application/json"


def test_example_collections_are_independent() -> None:
    examples = list_examples()
    examples[0]["request"]["url"] = "https://changed.example.com"
    assert list_examples()[0]["request"]["url"] != "https://changed.example.com"

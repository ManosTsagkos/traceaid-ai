"""Safe cURL, Python, pytest, and Markdown artifact generation."""

from __future__ import annotations

import json
import re
import shlex
from pprint import pformat

from traceaid.models import (
    DiagnosisReport,
    GeneratedArtifacts,
    ObservedResponse,
    ProbeResult,
    RequestSpec,
)
from traceaid.services.redaction import is_sensitive_name, redact_request


def _body_as_json(request: RequestSpec) -> str | None:
    if request.body is None:
        return None
    if isinstance(request.body, str):
        return request.body
    return json.dumps(request.body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _environment_name(header_name: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", header_name).strip("_").upper()
    return f"TRACEAID_{safe_name or 'SECRET'}"


def generate_corrected_curl(request: RequestSpec) -> str:
    """Create a reproducible cURL command with all secrets removed."""

    safe = redact_request(request)
    parts = ["curl", "--request", safe.method, shlex.quote(safe.url)]
    for name in sorted(safe.headers, key=str.casefold):
        value = safe.headers[name]
        if is_sensitive_name(name):
            value = f"<set {_environment_name(name)}>"
        parts.extend(["--header", shlex.quote(f"{name}: {value}")])
    body = _body_as_json(safe)
    if body is not None:
        parts.extend(["--data-raw", shlex.quote(body)])
    return " \\\n  ".join(parts)


def _python_headers(request: RequestSpec) -> tuple[str, bool]:
    safe = redact_request(request)
    entries: list[str] = []
    needs_os = False
    for name in sorted(safe.headers, key=str.casefold):
        if is_sensitive_name(name):
            value = f'os.environ["{_environment_name(name)}"]'
            needs_os = True
        else:
            value = repr(safe.headers[name])
        entries.append(f"    {name!r}: {value},")
    if not entries:
        return "{}", needs_os
    return "{\n" + "\n".join(entries) + "\n}", needs_os


def generate_python_snippet(request: RequestSpec) -> str:
    """Generate an executable httpx example that reads secrets from env vars."""

    safe = redact_request(request)
    headers, needs_os = _python_headers(request)
    lines = []
    if needs_os:
        lines.append("import os")
    lines.extend(["import httpx", "", f"headers = {headers}"])
    arguments = [repr(safe.method), repr(safe.url), "headers=headers", "timeout=8.0"]
    if safe.body is not None:
        if isinstance(safe.body, str):
            arguments.append(f"content={safe.body!r}")
        else:
            arguments.append(f"json={pformat(safe.body, sort_dicts=True, width=88)}")
    lines.extend(
        [
            "",
            f"response = httpx.request({', '.join(arguments)})",
            "response.raise_for_status()",
            "print(response.json())",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_pytest_test(
    request: RequestSpec,
    observed: ObservedResponse | ProbeResult | None = None,
) -> str:
    """Generate a small opt-in integration regression test."""

    safe = redact_request(request)
    headers, needs_os = _python_headers(request)
    imports = ["import httpx", "import pytest"]
    if needs_os:
        imports.insert(0, "import os")

    expected_note = "The original request failed"
    if observed and observed.status_code:
        expected_note += f" with HTTP {observed.status_code}"
    expected_note += "; the corrected request should now be successful."

    call_arguments = [repr(safe.method), repr(safe.url), "headers=headers"]
    if safe.body is not None:
        if isinstance(safe.body, str):
            call_arguments.append(f"content={safe.body!r}")
        else:
            call_arguments.append(f"json={pformat(safe.body, sort_dicts=True, width=84)}")

    lines = [
        *imports,
        "",
        "",
        "@pytest.mark.integration",
        "def test_corrected_api_request_regression() -> None:",
        f'    """{expected_note}"""',
        *[f"    {line}" if line else "" for line in f"headers = {headers}".splitlines()],
        "",
        "    with httpx.Client(timeout=8.0, follow_redirects=False) as client:",
        f"        response = client.request({', '.join(call_arguments)})",
        "",
        "    assert response.status_code < 400, response.text[:500]",
    ]
    return "\n".join(lines) + "\n"


def _markdown_text(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def generate_markdown_report(report: DiagnosisReport) -> str:
    """Render a portable incident report from an already-redacted model."""

    diagnosis = report.diagnosis
    evidence = (
        "\n".join(f"- {_markdown_text(item)}" for item in diagnosis.evidence) or "- None supplied"
    )
    fixes = "\n".join(
        f"{index}. {_markdown_text(item)}" for index, item in enumerate(diagnosis.fix_steps, 1)
    )
    probe_line = "Not requested"
    if report.probe is not None:
        if report.probe.attempted:
            probe_line = (
                f"HTTP {report.probe.status_code}"
                if report.probe.status_code
                else report.probe.error or "Attempted"
            )
        else:
            probe_line = report.probe.error or "Blocked"

    return f"""# TraceAid diagnosis `{_markdown_text(report.id)}`

| Field | Value |
|---|---|
| Created | {_markdown_text(report.created_at)} |
| Mode | {_markdown_text(report.mode)} |
| Request | `{_markdown_text(report.redacted_request.method)} {_markdown_text(report.redacted_request.url)}` |
| Probe | {_markdown_text(probe_line)} |
| Severity | {_markdown_text(diagnosis.severity.value)} |
| Confidence | {diagnosis.confidence:.0%} |

## {_markdown_text(diagnosis.title)}

{_markdown_text(diagnosis.summary)}

**Likely cause:** {_markdown_text(diagnosis.likely_cause)}

### Evidence

{evidence}

### Recommended fix

{fixes}

### Corrected cURL

```bash
{report.artifacts.corrected_curl}
```

### Python reproduction

```python
{report.artifacts.python_snippet.rstrip()}
```

### Pytest regression

```python
{report.artifacts.pytest_test.rstrip()}
```
"""


def build_artifacts(
    request: RequestSpec,
    observed: ObservedResponse | ProbeResult | None = None,
) -> GeneratedArtifacts:
    """Build code artifacts; Markdown is attached after the report is created."""

    return GeneratedArtifacts(
        corrected_curl=generate_corrected_curl(request),
        python_snippet=generate_python_snippet(request),
        pytest_test=generate_pytest_test(request, observed),
        markdown_report="",
    )


__all__ = [
    "build_artifacts",
    "generate_corrected_curl",
    "generate_markdown_report",
    "generate_pytest_test",
    "generate_python_snippet",
]

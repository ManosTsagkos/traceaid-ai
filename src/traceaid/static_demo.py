"""Build a credential-free portfolio demo from the real diagnosis pipeline.

GitHub Pages cannot run Python. Its interactive view therefore presents prepared,
redacted reports produced here; it never pretends to diagnose arbitrary input.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Any

from traceaid.config import Settings
from traceaid.demo_data import list_examples
from traceaid.models import IncidentRequest
from traceaid.services.diagnosis import DiagnosisService
from traceaid.services.redaction import redact_request
from traceaid.services.report_generator import finalize_report


async def prepare_examples() -> list[dict[str, Any]]:
    """Use synthetic examples only, ignoring any developer API key or probe setting."""

    service = DiagnosisService(Settings(openai_api_key=None, enable_live_probes=False))
    prepared: list[dict[str, Any]] = []
    for example in list_examples():
        payload = {key: example[key] for key in ("request", "observed")}
        incident = IncidentRequest.model_validate(payload)
        report = await service.diagnose(incident)
        # Stable generated assets keep reviews/diffs reproducible.
        report = finalize_report(
            report.model_copy(
                update={"id": f"demo_{example['id']}", "created_at": "2026-10-03T00:00:00Z"}
            )
        )
        prepared.append(
            {
                **example,
                "request": redact_request(incident.request).model_dump(mode="json"),
                "diagnosis": report.diagnosis.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            }
        )
    return prepared


async def build_demo(output: Path) -> Path:
    """Write a relocatable, self-contained static site without deleting any directory."""

    web = Path(__file__).parent / "web"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("app.js", "styles.css"):
        copyfile(web / name, output / name)
    html = (web / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/styles.css"', 'href="./styles.css"')
    html = html.replace(
        '<script src="/static/app.js" defer></script>',
        '<script src="./demo-data.js" defer></script>\n    <script src="./app.js" defer></script>',
    )
    html = html.replace("<body>", '<body data-static-demo="true">')
    (output / "index.html").write_text(html, encoding="utf-8")
    data = {"kind": "prepared-rules-reports", "examples": await prepare_examples()}
    # External data script works on Pages subpaths, localhost, and file:// previews.
    encoded = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    (output / "demo-data.js").write_text(f"window.TRACEAID_DEMO = {encoded};\n", encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    return output


async def check_demo(output: Path) -> bool:
    """Check generated content without touching an existing site's files."""

    with TemporaryDirectory(prefix="traceaid-demo-") as directory:
        expected = await build_demo(Path(directory))
        return all(
            (output / source.name).is_file()
            and source.read_bytes() == (output / source.name).read_bytes()
            for source in expected.iterdir()
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("site"))
    parser.add_argument(
        "--check", action="store_true", help="Fail if generated demo files are stale"
    )
    args = parser.parse_args()
    if args.check:
        if not asyncio.run(check_demo(args.output)):
            parser.exit(status=1, message="Prepared demo is missing or stale; rebuild it.\n")
        print("Prepared demo is current.")
        return
    output = asyncio.run(build_demo(args.output))
    print(f"Prepared interactive demo: {output.resolve()}")


if __name__ == "__main__":
    main()

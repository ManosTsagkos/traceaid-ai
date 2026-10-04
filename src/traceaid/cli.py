"""Command-line interface for CI jobs and terminal-first workflows."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from traceaid.demo_data import get_example, list_examples
from traceaid.models import IncidentRequest
from traceaid.services.diagnosis import DiagnosisService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="traceaid",
        description="Turn failed REST API calls into evidence-backed fixes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose = subparsers.add_parser("diagnose", help="Diagnose an incident JSON file")
    diagnose.add_argument(
        "input",
        help="Path to an incident JSON file, or '-' to read standard input",
    )
    diagnose.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json)",
    )
    diagnose.add_argument("--use-ai", action="store_true", help="Enable LLM enrichment")
    diagnose.add_argument("--probe", action="store_true", help="Execute the HTTP request")

    demo = subparsers.add_parser("demo", help="Run a built-in incident")
    demo.add_argument(
        "id",
        nargs="?",
        default="validation-error",
        choices=tuple(example["id"] for example in list_examples()),
    )
    demo.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    demo.add_argument("--use-ai", action="store_true", help="Enable LLM enrichment")
    return parser


def _read_payload(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Incident JSON must contain an object at the top level")
    for metadata_key in ("id", "name", "description", "category"):
        data.pop(metadata_key, None)
    return data


async def _run(args: argparse.Namespace) -> int:
    if args.command == "demo":
        payload = get_example(args.id)
        if payload is None:  # argparse choices make this a defensive branch
            raise ValueError(f"Unknown demo: {args.id}")
        for key in ("id", "name", "description", "category"):
            payload.pop(key, None)
        payload["use_ai"] = bool(args.use_ai)
    else:
        payload = _read_payload(args.input)
        if args.use_ai:
            payload["use_ai"] = True
        if args.probe:
            payload["execute_probe"] = True

    incident = IncidentRequest.model_validate(payload)
    report = await DiagnosisService().diagnose(incident)
    if args.format == "markdown":
        print(report.artifacts.markdown_report)
    else:
        print(report.model_dump_json(indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and return a conventional process exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        parser.exit(status=2, message=f"traceaid: {exc}\n")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Smoke-test an installed wheel, including its CLI and packaged web assets."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import traceaid
from traceaid.main import create_app


def main() -> None:
    package = Path(traceaid.__file__).resolve()
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(f"Expected an installed wheel inside the environment, got {package}")

    with TestClient(create_app()) as client:
        response = client.get("/")
        if response.status_code != 200 or "TraceAid AI" not in response.text:
            raise RuntimeError("Installed wheel did not serve the web application")
        for asset in ("app.js", "styles.css"):
            if client.get(f"/static/{asset}").status_code != 200:
                raise RuntimeError(f"Installed wheel is missing {asset}")
        response = client.post("/api/v1/examples/expired-token/diagnose")
        if response.status_code != 200:
            raise RuntimeError("Installed wheel could not diagnose a built-in example")
        if response.json()["diagnosis"]["category"] != "authentication":
            raise RuntimeError("Installed wheel returned an unexpected diagnosis")
        if "demo-expired-token" in response.text:
            raise RuntimeError("Installed wheel did not redact the synthetic credential")

    with tempfile.TemporaryDirectory(prefix="traceaid-wheel-") as directory:
        result = subprocess.run(
            [sys.executable, "-m", "traceaid", "demo", "expired-token", "--format", "json"],
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
        )
        if json.loads(result.stdout)["diagnosis"]["category"] != "authentication":
            raise RuntimeError("Installed CLI returned an unexpected diagnosis")
        output = Path(directory) / "site"
        for arguments in (["--output", str(output)], ["--output", str(output), "--check"]):
            subprocess.run(  # noqa: S603 - fixed executable and trusted package command
                [sys.executable, "-m", "traceaid.static_demo", *arguments],
                cwd=directory,
                check=True,
                capture_output=True,
                text=True,
            )
        if not (output / "demo-data.js").is_file():
            raise RuntimeError("Installed wheel did not generate the prepared demo")

    print("Installed wheel: web assets, diagnosis, CLI, and prepared demo passed")


if __name__ == "__main__":
    main()

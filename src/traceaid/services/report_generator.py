"""Report assembly helpers kept separate from diagnosis orchestration."""

from __future__ import annotations

from traceaid.models import DiagnosisReport
from traceaid.services.generators import generate_markdown_report


def finalize_report(report: DiagnosisReport) -> DiagnosisReport:
    """Return a copy with its self-contained Markdown artifact attached."""

    markdown = generate_markdown_report(report)
    artifacts = report.artifacts.model_copy(update={"markdown_report": markdown})
    return report.model_copy(update={"artifacts": artifacts})


__all__ = ["finalize_report", "generate_markdown_report"]

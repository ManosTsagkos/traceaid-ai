"""High-level orchestration for one TraceAid diagnosis run."""

from __future__ import annotations

from typing import Literal

from traceaid.config import Settings, get_settings
from traceaid.models import DiagnosisReport, IncidentRequest, ReportMetadata
from traceaid.services.generators import build_artifacts
from traceaid.services.llm import DemoLLMProvider, LLMProvider, get_llm_provider
from traceaid.services.probe import ProbeClient
from traceaid.services.redaction import redact_request
from traceaid.services.report_generator import finalize_report
from traceaid.services.rules_engine import RULES_VERSION, analyze_request, suggest_correction


class DiagnosisService:
    """Combine deterministic analysis, an optional probe, and optional AI."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        probe_client: ProbeClient | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.probe_client = probe_client or ProbeClient(self.settings)
        self.llm_provider = llm_provider or get_llm_provider(self.settings)

    async def diagnose(self, request: IncidentRequest) -> DiagnosisReport:
        warnings: list[str] = []
        probe = None

        if request.execute_probe:
            probe = await self.probe_client.execute(request.request)
            if not probe.attempted and probe.error:
                warnings.append(probe.error)
            elif probe.redirect_location:
                warnings.append(
                    "The probe did not follow the redirect; validate the new target separately."
                )

        # User-supplied failure evidence has precedence. A current probe remains
        # attached to the report and may show that an intermittent issue cleared.
        effective_observed = request.observed or (probe if probe and probe.attempted else None)
        diagnosis = analyze_request(request.request, effective_observed)

        provider_name: str | None = None
        if request.use_ai:
            provider_name = self.llm_provider.name
            try:
                diagnosis = await self.llm_provider.refine(
                    request=request.request,
                    observed=effective_observed,
                    baseline=diagnosis,
                    context=request.context,
                )
            except Exception:
                # External provider failures never make diagnosis unavailable.
                diagnosis = await DemoLLMProvider().refine(
                    request=request.request,
                    observed=effective_observed,
                    baseline=diagnosis,
                    context=request.context,
                )
                warnings.append("AI refinement was unavailable; deterministic fallback was used.")
            else:
                if diagnosis.source == "demo" and provider_name != "demo":
                    warnings.append(
                        "AI refinement was unavailable; deterministic fallback was used."
                    )

        corrected_request = suggest_correction(request.request, diagnosis, effective_observed)
        artifacts = build_artifacts(corrected_request, effective_observed)

        probe_performed = bool(probe and probe.attempted)
        mode: Literal["rules", "probe", "ai", "hybrid", "demo"]
        if request.use_ai and diagnosis.source == "demo":
            mode = "demo"
        elif request.use_ai and probe_performed:
            mode = "hybrid"
        elif request.use_ai:
            mode = "ai"
        elif probe_performed:
            mode = "probe"
        else:
            mode = "rules"

        report = DiagnosisReport(
            mode=mode,
            redacted_request=redact_request(request.request),
            diagnosis=diagnosis,
            artifacts=artifacts,
            probe=probe,
            metadata=ReportMetadata(
                rules_version=RULES_VERSION,
                llm_provider=provider_name,
                probe_requested=request.execute_probe,
                probe_performed=probe_performed,
                warnings=warnings,
            ),
        )
        return finalize_report(report)


__all__ = ["DiagnosisService"]

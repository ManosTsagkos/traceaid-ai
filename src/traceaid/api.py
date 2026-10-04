"""HTTP API for TraceAid AI."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from traceaid import __version__
from traceaid.demo_data import get_example, list_examples
from traceaid.models import DiagnosisReport, IncidentRequest, RequestSpec
from traceaid.services.curl_parser import CurlParseError, parse_curl
from traceaid.services.diagnosis import DiagnosisService

router = APIRouter(prefix="/api/v1", tags=["diagnostics"])


class CurlParseRequest(BaseModel):
    """A cURL command submitted for safe, local-only parsing."""

    command: str = Field(min_length=4, max_length=50_000)


class ExampleSummary(BaseModel):
    """Metadata and ready-to-submit payload for a demo incident."""

    id: str
    name: str
    description: str
    category: str
    payload: dict[str, Any]


@lru_cache(maxsize=1)
def get_diagnosis_service() -> DiagnosisService:
    """Keep stateless clients reusable while loading configuration once."""

    return DiagnosisService()


DiagnosisServiceDependency = Annotated[DiagnosisService, Depends(get_diagnosis_service)]


@router.get("/meta")
async def metadata() -> dict[str, Any]:
    """Describe capabilities for clients and deployment smoke tests."""

    return {
        "name": "TraceAid AI",
        "version": __version__,
        "capabilities": [
            "secret-redaction",
            "rules-diagnostics",
            "safe-http-probes",
            "structured-llm-analysis",
            "regression-test-generation",
        ],
        "default_mode": "rules",
    }


@router.get("/examples", response_model=list[ExampleSummary])
async def examples() -> list[ExampleSummary]:
    """Return credential-free examples that work without network access."""

    summaries: list[ExampleSummary] = []
    for example in list_examples():
        metadata_fields = {
            key: example.pop(key) for key in ("id", "name", "description", "category")
        }
        summaries.append(ExampleSummary(payload=example, **metadata_fields))
    return summaries


@router.post("/examples/{example_id}/diagnose", response_model=DiagnosisReport)
async def diagnose_example(
    example_id: str,
    service: DiagnosisServiceDependency,
) -> DiagnosisReport:
    """Run a built-in incident through the exact same production pipeline."""

    example = get_example(example_id)
    if example is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown example")
    for key in ("id", "name", "description", "category"):
        example.pop(key, None)
    return await service.diagnose(IncidentRequest.model_validate(example))


@router.post("/parse-curl", response_model=RequestSpec)
async def parse_curl_command(payload: CurlParseRequest) -> RequestSpec:
    """Convert a cURL command into the typed request editor format."""

    try:
        return parse_curl(payload.command)
    except CurlParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/diagnose", response_model=DiagnosisReport)
async def diagnose(
    payload: IncidentRequest,
    service: DiagnosisServiceDependency,
) -> DiagnosisReport:
    """Diagnose one failed request and generate reproducible fix artifacts."""

    try:
        return await service.diagnose(payload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

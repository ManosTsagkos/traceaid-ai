"""FastAPI application entry point."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from traceaid import __version__
from traceaid.api import router
from traceaid.config import get_settings

LOGGER = logging.getLogger("traceaid")
WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app() -> FastAPI:
    """Application factory used by Uvicorn and integration tests."""

    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    application = FastAPI(
        title="TraceAid AI",
        summary="Turn failed API calls into evidence-backed fixes.",
        description=(
            "A secure diagnostic pipeline combining deterministic HTTP rules, "
            "optional structured LLM analysis, and executable regression artifacts."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/api/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # pragma: no cover - defensive production boundary
            LOGGER.exception("Unhandled request error", extra={"request_id": request_id})
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "An unexpected error occurred",
                    "request_id": request_id,
                },
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    application.include_router(router)

    @application.get("/api/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if WEB_DIR.exists():
        application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @application.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return application


app = create_app()

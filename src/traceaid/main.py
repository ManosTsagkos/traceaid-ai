"""FastAPI application entry point."""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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
        docs_url=None,
        redoc_url=None,
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
        # ASGI mounts retain the public prefix in path; a proxy may have
        # already stripped it. Match the same route-relative path in both
        # cases, and only remove a prefix at a complete path boundary.
        route_path: str = request.scope["path"]
        root_path: str = request.scope.get("root_path", "")
        if root_path and route_path == root_path:
            route_path = ""
        elif root_path and route_path.startswith(f"{root_path}/"):
            route_path = route_path[len(root_path) :]
        documentation = route_path in {"/docs", "/redoc"}
        if documentation:
            request.state.csp_nonce = secrets.token_urlsafe(24)
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
        if documentation:
            # The API documentation loads FastAPI's CDN assets. Authorize its
            # bootstrap with a fresh nonce; keep the application policy strict.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                f"script-src 'self' 'nonce-{request.state.csp_nonce}' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self'; font-src 'self'; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    application.include_router(router)

    @application.get("/docs", include_in_schema=False)
    async def swagger_documentation(request: Request) -> HTMLResponse:
        response = get_swagger_ui_html(
            openapi_url=f"{request.scope.get('root_path', '')}/api/openapi.json",
            title="TraceAid AI - Swagger UI",
        )
        html = (
            bytes(response.body)
            .decode("utf-8")
            .replace("<script>", f'<script nonce="{request.state.csp_nonce}">')
        )
        return HTMLResponse(html)

    @application.get("/redoc", include_in_schema=False)
    async def redoc_documentation(request: Request) -> HTMLResponse:
        return get_redoc_html(
            openapi_url=f"{request.scope.get('root_path', '')}/api/openapi.json",
            title="TraceAid AI - ReDoc",
            with_google_fonts=False,
        )

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

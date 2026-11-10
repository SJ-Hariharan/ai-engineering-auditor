"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import ai, audits, auth, projects, remediation
from app.core.body_limit import BodyLimitMiddleware
from app.core.config import get_settings
from app.core.database import init_db

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "x-auditor-client"


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        yield

    app = FastAPI(title="AI Engineering Auditor", version="0.1.0", lifespan=lifespan,
                  docs_url=None if settings.is_production else "/api/docs",
                  openapi_url=None if settings.is_production else "/api/openapi.json")

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        # CSRF: state-changing requests must carry a custom header. Browsers cannot add
        # custom headers cross-origin without a CORS preflight, which only allows our origins.
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/") \
                and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["content-type", CSRF_HEADER])
    # Outermost: refuse oversized bodies before anything parses them (SEC-04). Uploads are the
    # largest legitimate body; allow 1 MiB of multipart overhead on top.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    for r in (auth.router, projects.router, audits.router, remediation.router, ai.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

"""FastAPI entry point.

Run locally (never expose this port directly):
    uvicorn app.main:app --proxy-headers --forwarded-allow-ips=127.0.0.1 \
        --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.models import OkResponse
from .config import (
    APP_NAME,
    CORS_ORIGINS,
    ENABLE_API_DOCS,
    TRUSTED_PROXY,
    VERSION,
    WEB_CONCURRENCY,
)
from .db import clear_expired_sessions, init_db
from .errors import ApiError, error_payload, from_http_exception
from .routes import (
    auth,
    dashboard,
    export,
    gallery_admin,
    health,
    media,
    media_serve,
    pages,
    posts,
    profile,
    projects,
    public,
    taxonomy,
    users,
)
from .routes import (
    settings as settings_routes,
)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

logger = logging.getLogger("mztlab.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if WEB_CONCURRENCY > 1:
        raise RuntimeError(
            "3.0.0 keeps its rate limiter and settings cache in process memory; "
            "run a single worker (WEB_CONCURRENCY=1). Multi-worker deployments "
            "would silently multiply every quota."
        )
    init_db()
    clear_expired_sessions()
    from .images import AVIF_SUPPORTED, WEBP_SUPPORTED

    logger.info(
        "image pipeline: avif=%s webp=%s", AVIF_SUPPORTED, WEBP_SUPPORTED
    )
    if not AVIF_SUPPORTED:
        logger.warning("AVIF encoder unavailable; serving WebP/JPEG derivatives only")
    yield


app = FastAPI(
    title=f"{APP_NAME} API",
    version=VERSION,
    lifespan=lifespan,
    # The API docs reveal the full attack surface. Expose them only when
    # BLOG_ENABLE_API_DOCS=true is set explicitly (development).
    docs_url="/api/docs" if ENABLE_API_DOCS else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if ENABLE_API_DOCS else None,
)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def protect_admin_and_add_headers(request: Request, call_next):
    path = request.url.path
    # A custom header cannot be attached cross-origin without a CORS preflight,
    # and this API ships no permissive CORS policy by default.
    if (
        path.startswith("/api/admin")
        and request.method in UNSAFE_METHODS
        and request.headers.get("x-blog-request") != "1"
    ):
        return JSONResponse(
            status_code=403,
            content=error_payload(
                "request.csrf_header_missing", "请求缺少校验头，请刷新页面后重试"
            ),
        )

    # The ingress may generate X-Request-ID; when it does not, the application
    # generates one so nginx and app logs can still be correlated.
    request_id = (request.headers.get("x-request-id") or "").strip()[:128]
    if not request_id:
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers.setdefault("X-Request-ID", request_id)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
    )
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # Covers both FastAPI's HTTPException and Starlette's built-in 404/405 raised
    # before a route matches, so every error response keeps the same envelope.
    return JSONResponse(
        status_code=exc.status_code,
        content=from_http_exception(exc),
        headers=exc.headers or None,
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    if exc.status_code >= 500:
        logger.error("[%s] %s %s: %s", request_id, request.method, request.url.path, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, exc.field),
        headers={**(exc.headers or {}), "X-Request-ID": request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """One readable message, with the offending field when there is one."""
    message = "请求参数不正确"
    field: str | None = None
    errors = exc.errors()
    if errors:
        first = errors[0]
        message = str(first.get("msg", "")).removeprefix("Value error, ") or message
        location = [str(part) for part in first.get("loc", []) if part not in ("body", "query")]
        field = ".".join(location) or None
    return JSONResponse(
        status_code=422,
        content=error_payload("request.validation_failed", message, field),
    )


@app.exception_handler(OverflowError)
async def overflow_error_handler(request: Request, exc: OverflowError) -> JSONResponse:
    # Huge integer ids used to reach SQLite and crash with a 500. Reject them.
    logger.warning("overflow on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=400, content=error_payload("request.invalid", "参数超出范围")
    )


@app.exception_handler(sqlite3.Error)
async def database_error_handler(
    request: Request, exc: sqlite3.Error
) -> JSONResponse:
    logger.exception("database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_payload("server.internal_error", "服务器内部错误"),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak tracebacks, file paths or dependency details to the client.
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_payload("server.internal_error", "服务器内部错误"),
    )


app.include_router(auth.router, prefix="/api")
app.include_router(public.router, prefix="/api")
# Admin API is split per resource (BC-07): no `?type=` multi-resource router.
app.include_router(posts.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(pages.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(taxonomy.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(gallery_admin.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(health.router, prefix="/api")
# Public media files: originals and generated AVIF/WebP/JPEG derivatives. The
# operator nginx routes `/media` here; direct object-storage URLs bypass it.
app.include_router(media_serve.router)


@app.get("/", response_model=OkResponse)
def root() -> dict:
    # Deliberately terse: no version, docs path or deployment details.
    return {"ok": True}

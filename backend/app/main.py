"""FastAPI entry point.

Run locally (never expose this port directly):
    uvicorn app.main:app --no-proxy-headers --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import APP_NAME, CORS_ORIGINS, ENABLE_API_DOCS
from .db import clear_expired_sessions, init_db
from .routes import admin, auth, gallery_admin, media, media_serve, public, users

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

logger = logging.getLogger("mztlab.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
            content={"detail": "请求缺少校验头，请刷新页面后重试"},
        )

    response = await call_next(request)
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


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return one readable Chinese message instead of the raw validation list."""
    detail = "请求参数不正确"
    errors = exc.errors()
    if errors:
        message = str(errors[0].get("msg", "")).removeprefix("Value error, ")
        detail = message or detail
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(OverflowError)
async def overflow_error_handler(request: Request, exc: OverflowError) -> JSONResponse:
    # Huge integer ids used to reach SQLite and crash with a 500. Reject them.
    logger.warning("overflow on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=400, content={"detail": "参数超出范围"})


@app.exception_handler(sqlite3.Error)
async def database_error_handler(
    request: Request, exc: sqlite3.Error
) -> JSONResponse:
    logger.exception("database error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak tracebacks, file paths or dependency details to the client.
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


app.include_router(auth.router, prefix="/api")
app.include_router(public.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(gallery_admin.router, prefix="/api")
app.include_router(media.router, prefix="/api")
# Public media files: originals and generated AVIF/WebP/JPEG derivatives. The
# Astro server proxies this path, and direct object-storage URLs bypass it.
app.include_router(media_serve.router)


@app.get("/")
def root() -> dict:
    # Deliberately terse: no version, docs path or deployment details.
    return {"ok": True}

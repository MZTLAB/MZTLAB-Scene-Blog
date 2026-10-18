"""FastAPI entry point.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, CORS_ORIGINS, UPLOAD_DIR, VERSION
from .db import clear_expired_sessions, init_db
from .routes import admin, auth, gallery_admin, media, public, users

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    clear_expired_sessions()
    yield


app = FastAPI(
    title=f"{APP_NAME} API",
    version=VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
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
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(auth.router, prefix="/api")
app.include_router(public.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(gallery_admin.router, prefix="/api")
app.include_router(media.router, prefix="/api")

# Public media files. Filenames are random and formats are validated, so this
# is safe to serve directly; in production the Astro server proxies it.
app.mount("/media", StaticFiles(directory=UPLOAD_DIR, check_dir=False), name="media")


@app.get("/")
def root() -> dict:
    return {
        "name": APP_NAME,
        "version": VERSION,
        "docs": "/api/docs",
        "message": "The MZTLAB site is served by Astro on port 4321 (theme: Scene).",
    }

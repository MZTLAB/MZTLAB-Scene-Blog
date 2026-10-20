"""Application configuration.

Everything is intentionally environment-variable driven so the same code can
run locally, in a container, or on a small VPS without changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

# Load .env from the repo root first, then backend/.env (the latter wins).
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

APP_NAME = "MZTLAB"
VERSION = "2.3.0"

# Largest integer SQLite can bind (signed 64-bit). Request parameters are
# capped to this so oversized ids return 422 instead of an unhandled 500.
MAX_SQLITE_INT = 2**63 - 1


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DATA_DIR = Path(os.getenv("BLOG_DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
DB_PATH = Path(os.getenv("BLOG_DB_PATH", str(DATA_DIR / "blog.db"))).expanduser().resolve()
UPLOAD_DIR = Path(os.getenv("BLOG_UPLOAD_DIR", str(DATA_DIR / "uploads"))).expanduser().resolve()
# Generated AVIF/WebP/JPEG derivatives live outside the original upload tree so
# backups of `uploads/` stay canonical and a cache can be discarded safely.
IMAGE_CACHE_DIR = Path(
    os.getenv("BLOG_IMAGE_CACHE_DIR", str(DATA_DIR / "cache"))
).expanduser().resolve()
# AVIF/WebP encoding is CPU heavy; a small ceiling keeps a burst of image
# requests from starving the rest of the API.
IMAGE_ENCODE_WORKERS = max(1, min(8, int(os.getenv("BLOG_IMAGE_ENCODE_WORKERS", "2"))))
# Hard technical ceiling for the "full" (original resolution) derivative.
# 0 means "no cap beyond the original image width".
IMAGE_MAX_WIDTH_HARD_LIMIT = 8192

# Object storage. The admin panel writes these values into the settings table;
# environment variables are only a fallback (useful for Docker secrets). The
# secret key never leaves the process: it is never part of /api/site and the
# admin API only reports whether one is configured.
S3_ENV_FALLBACK = {
    "storage_backend": os.getenv("BLOG_STORAGE_BACKEND", ""),
    "storage_s3_endpoint": os.getenv("BLOG_S3_ENDPOINT", ""),
    "storage_s3_bucket": os.getenv("BLOG_S3_BUCKET", ""),
    "storage_s3_region": os.getenv("BLOG_S3_REGION", ""),
    "storage_s3_access_key": os.getenv("BLOG_S3_ACCESS_KEY", ""),
    "storage_s3_secret_key": os.getenv("BLOG_S3_SECRET_KEY", ""),
    "storage_s3_prefix": os.getenv("BLOG_S3_PREFIX", ""),
    "storage_public_base_url": os.getenv("BLOG_S3_PUBLIC_BASE_URL", ""),
}
S3_PATH_STYLE_ENV = _flag("BLOG_S3_PATH_STYLE", False)

FRONTEND_URL = os.getenv("BLOG_FRONTEND_URL", "http://127.0.0.1:4321").rstrip("/")
SITE_URL = os.getenv("BLOG_SITE_URL", "").rstrip("/")
SESSION_COOKIE = os.getenv("BLOG_SESSION_COOKIE", "mztlab_session")
# Shorter default than the previous 14 days. Rotate on every login and revoke
# on password/permission changes (see deps.py / routes/users.py).
SESSION_DAYS = max(1, min(30, int(os.getenv("BLOG_SESSION_DAYS", "7"))))

# `Secure` cookies only work under HTTPS. When BLOG_COOKIE_SECURE is not set we
# derive it from the configured public URL so an HTTPS deployment is secure by
# default; a plain-HTTP local setup keeps working.
_public_url = (SITE_URL or FRONTEND_URL).lower()
_https_deployment = _public_url.startswith("https://")
COOKIE_SECURE = _flag("BLOG_COOKIE_SECURE", _https_deployment)

# Shared secret between the Astro proxy and FastAPI. When set, the backend only
# trusts `X-Blog-Real-IP` from a request that carries this header, so a client
# cannot forge its source address to bypass login rate limits. scripts/run.py
# generates it automatically for local runs; Docker deployments set it in the
# environment of both containers.
PROXY_SECRET = os.getenv("BLOG_PROXY_SECRET", "").strip()
PROXY_SECRET_HEADER = "x-blog-proxy-secret"
REAL_IP_HEADER = "x-blog-real-ip"

# Swagger/OpenAPI are useful while developing but hand attackers a full map of
# the API. Off by default; enable explicitly in development if needed.
ENABLE_API_DOCS = _flag("BLOG_ENABLE_API_DOCS", False)

# Optional bootstrap administrator. When both values are set and no user exists,
# the account is created at startup. The normal flow is the /setup web page.
BOOTSTRAP_ADMIN_USER = os.getenv("BLOG_ADMIN_USER", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BLOG_ADMIN_PASSWORD", "")
BOOTSTRAP_ADMIN_NAME = os.getenv("BLOG_ADMIN_NAME", "MZTLAB").strip() or "MZTLAB"

SEED_DEMO = _flag("BLOG_SEED_DEMO", True)
MAX_UPLOAD_BYTES = int(os.getenv("BLOG_MAX_UPLOAD_MB", "12")) * 1024 * 1024
# Administrators ignore the configured upload policy; this technical ceiling
# keeps a single upload from exhausting memory/disk. Raise it deliberately.
ADMIN_MAX_UPLOAD_MB = max(
    1, int(os.getenv("BLOG_ADMIN_MAX_UPLOAD_MB", "200"))
)
ADMIN_MAX_UPLOAD_BYTES = ADMIN_MAX_UPLOAD_MB * 1024 * 1024
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("BLOG_CORS_ORIGINS", "").split(",")
    if origin.strip()
]

for directory in (DATA_DIR, UPLOAD_DIR, IMAGE_CACHE_DIR):
    directory.mkdir(parents=True, exist_ok=True)

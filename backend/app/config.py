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
VERSION = "2.1.0"

DATA_DIR = Path(os.getenv("BLOG_DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
DB_PATH = Path(os.getenv("BLOG_DB_PATH", str(DATA_DIR / "blog.db"))).expanduser().resolve()
UPLOAD_DIR = Path(os.getenv("BLOG_UPLOAD_DIR", str(DATA_DIR / "uploads"))).expanduser().resolve()

FRONTEND_URL = os.getenv("BLOG_FRONTEND_URL", "http://127.0.0.1:4321").rstrip("/")
SITE_URL = os.getenv("BLOG_SITE_URL", "").rstrip("/")
SESSION_COOKIE = os.getenv("BLOG_SESSION_COOKIE", "mztlab_session")
SESSION_DAYS = max(1, int(os.getenv("BLOG_SESSION_DAYS", "14")))
COOKIE_SECURE = os.getenv("BLOG_COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}

# Optional bootstrap administrator. When both values are set and no user exists,
# the account is created at startup. The normal flow is the /setup web page.
BOOTSTRAP_ADMIN_USER = os.getenv("BLOG_ADMIN_USER", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.getenv("BLOG_ADMIN_PASSWORD", "")
BOOTSTRAP_ADMIN_NAME = os.getenv("BLOG_ADMIN_NAME", "MZTLAB").strip() or "MZTLAB"

SEED_DEMO = os.getenv("BLOG_SEED_DEMO", "true").lower() in {"1", "true", "yes", "on"}
MAX_UPLOAD_BYTES = int(os.getenv("BLOG_MAX_UPLOAD_MB", "12")) * 1024 * 1024
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("BLOG_CORS_ORIGINS", "").split(",")
    if origin.strip()
]

for directory in (DATA_DIR, UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

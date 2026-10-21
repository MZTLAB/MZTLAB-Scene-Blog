"""Shared HTTP test fixtures.

Each test gets a fresh SQLite database; the app is exercised through the real
FastAPI stack (routing, middleware, error envelope, CSRF header) instead of
calling private helpers.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app.settings import invalidate_settings_cache


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "blog.db")
    invalidate_settings_cache()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    invalidate_settings_cache()


ADMIN = {
    "username": "owner",
    "password": "Str0ng-Passphrase!",
    "display_name": "站长",
    "site_title": "测试站点",
}


def setup_site(client: TestClient) -> None:
    response = client.post("/api/setup", json=ADMIN)
    assert response.status_code == 200, response.text


def admin_headers() -> dict[str, str]:
    # Unsafe admin requests must carry the CSRF marker header (main.py).
    return {"x-blog-request": "1"}

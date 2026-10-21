"""Export / import (3.x backup restore) HTTP integration tests.

The export document is the full 3.0.0 database shape plus the grouped settings
document; `POST /api/admin/import` replaces the whole site after validating the
document. These tests exercise the real FastAPI stack through `conftest.client`.
"""

from __future__ import annotations

import copy
import hashlib
import uuid
from collections.abc import Iterator
from contextlib import suppress
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import db, now_iso
from app.security import clear_login_failures
from app.storage import get_storage
from tests.conftest import ADMIN, admin_headers, setup_site

_SEEDED_FILES: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup_seeded_media_files() -> Iterator[None]:
    yield
    storage = get_storage()
    for filename in _SEEDED_FILES:
        with suppress(Exception):
            storage.delete(filename)
    _SEEDED_FILES.clear()


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), (200, 30, 20)).save(buffer, format="PNG")
    return buffer.getvalue()


def _seed_media(client: TestClient, *, with_file: bool = True) -> dict[str, Any]:
    """Insert a media row (+ optionally its binary) without the upload pipeline.

    The upload endpoint runs the image pipeline in the background; the backup
    format only needs the `media` row and a binary present in storage, so the
    test seeds those two pieces directly and exercises the rest through the API.
    """
    me = client.get("/api/auth/me").json()["user"]
    data = _png_bytes()
    digest = hashlib.sha1(data).hexdigest()
    filename = f"test-{uuid.uuid4().hex[:12]}.png"
    if with_file:
        get_storage().save(filename, data, "image/png")
        _SEEDED_FILES.append(filename)
    with db() as conn:
        cursor = conn.execute(
            """INSERT INTO media(filename, original_name, mime, size, width,
                                 height, alt, owner_id, exif, source_sha1,
                                 derivative_set, placeholder, created_at)
               VALUES (?, ?, 'image/png', ?, 16, 12, '', ?, '', ?, '', '', ?)""",
            (filename, filename, len(data), int(me["id"]), digest, now_iso()),
        )
        media_id = int(cursor.lastrowid)
    return {"id": media_id, "filename": filename, "source_sha1": digest}


def _login(client: TestClient) -> None:
    # A restore replaces users, so the previous session cookie is gone (SQLite
    # cascades the replaced sessions); the preserved password hash must work.
    # The login limiters are process-global, so clear the TestClient buckets
    # first (other tests may have consumed them).
    clear_login_failures("testclient", ADMIN["username"])
    response = client.post(
        "/api/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    assert response.status_code == 200, response.text


def _create_content(client: TestClient) -> dict[str, dict[str, Any]]:
    created: dict[str, dict[str, Any]] = {}
    specs = (
        ("post", "/api/admin/posts", {
            "title": "备份文章",
            "content_md": "## 小标题\n\n正文第一段。",
            "status": "published",
            "tags": ["随笔"],
            "categories": ["日志"],
        }),
        ("project", "/api/admin/projects", {
            "title": "备份项目",
            "content_md": "项目正文",
            "status": "published",
            "project_year": "2026",
            "project_role": "设计",
            "project_kind": "代码",
            "project_url": "https://example.com",
        }),
        ("page", "/api/admin/pages", {
            "title": "关于备份",
            "slug": "about-backup",
            "content_md": "关于页正文",
            "status": "published",
        }),
    )
    for kind, path, payload in specs:
        response = client.post(path, json=payload, headers=admin_headers())
        assert response.status_code == 201, (path, response.text)
        created[kind] = response.json()
    return created


def _create_gallery_and_photo(client: TestClient) -> dict[str, Any]:
    media_item = _seed_media(client)
    gallery = client.post(
        "/api/admin/galleries",
        json={"title": "备份相册", "slug": "backup-gallery", "status": "published"},
        headers=admin_headers(),
    )
    assert gallery.status_code in {200, 201}, gallery.text
    gallery_item = gallery.json()
    photo = client.post(
        "/api/admin/photos",
        json={
            "media_id": media_item["id"],
            "gallery_id": gallery_item["id"],
            "title": "备份照片",
        },
        headers=admin_headers(),
    )
    assert photo.status_code in {200, 201}, photo.text
    return {"media": media_item, "gallery": gallery_item, "photo": photo.json()}


def _prepare_site(client: TestClient) -> dict[str, Any]:
    setup_site(client)
    content = _create_content(client)
    gallery = _create_gallery_and_photo(client)
    settings = client.patch(
        "/api/admin/settings",
        json={
            "site": {"site_title": "备份站点"},
            "appearance": {"accent": "#112233"},
            "copy": {"photos_title": "相片"},
        },
        headers=admin_headers(),
    )
    assert settings.status_code == 200, settings.text
    return {"content": content, "gallery": gallery}


def _export(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/admin/export")
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers.get("content-disposition", "")
    return response.json()


def _import(
    client: TestClient,
    document: dict[str, Any],
    *,
    confirm: bool = True,
    query: str | None = None,
) -> Any:
    payload = copy.deepcopy(document)
    if confirm:
        payload["confirm"] = True
    else:
        payload.pop("confirm", None)
    url = "/api/admin/import" + (f"?confirm={query}" if query else "")
    return client.post(url, json=payload, headers=admin_headers())


def _canonical(document: dict[str, Any]) -> dict[str, Any]:
    """Projection that must survive a restore (ignores exported_at/ordering)."""
    return {
        "settings": document["settings"],
        "users": sorted(
            (
                user["username"],
                user["role"],
                user["password_hash"],
                user["is_active"],
            )
            for user in document["users"]
        ),
        "posts": sorted(
            (
                post["type"],
                post["slug"],
                post["title"],
                post["content_md"],
                post["status"],
                post["owner_id"],
                post["featured"],
            )
            for post in document["posts"]
        ),
        "project_details": sorted(
            (
                detail["post_id"],
                detail["kind"],
                detail["year"],
                detail["role"],
                detail["client"],
                detail["url"],
            )
            for detail in document["project_details"]
        ),
        "taxonomy_terms": sorted(
            (term["kind"], term["name"], term["slug"], term["description"])
            for term in document["taxonomy_terms"]
        ),
        "post_terms": sorted(
            (link["post_id"], link["term_id"]) for link in document["post_terms"]
        ),
        "galleries": sorted(
            (gallery["slug"], gallery["title"], gallery["status"], gallery["owner_id"])
            for gallery in document["galleries"]
        ),
        "photos": sorted(
            (
                photo["filename"],
                photo["gallery_id"],
                photo["media_id"],
                photo["title"],
                photo["hide_download_link"],
            )
            for photo in document["photos"]
        ),
        "media": sorted(
            (media["filename"], media["mime"], media["size"], media["owner_id"])
            for media in document["media"]
        ),
    }


def _counts(document: dict[str, Any]) -> dict[str, int]:
    return {
        key: len(document[key])
        for key in (
            "users",
            "posts",
            "project_details",
            "taxonomy_terms",
            "post_terms",
            "revisions",
            "galleries",
            "photos",
            "media",
            "media_derivatives",
        )
    }


class TestExportFormat:
    def test_export_is_a_complete_v3_backup(self, client: TestClient) -> None:
        _prepare_site(client)
        document = _export(client)

        assert document["format"] == "mztlab-scene-export"
        assert document["version"] == 3
        assert document["exported_at"]

        # Full grouped settings, not only the public projection.
        assert set(document["settings"]) == {
            "site", "appearance", "copy", "upload", "advanced"
        }
        assert document["settings"]["site"]["site_title"] == "备份站点"
        assert "image" in document["settings"]["advanced"]

        # Users travel with the backup so a restore can sign in.
        assert document["users"]
        assert document["users"][0]["username"] == ADMIN["username"]
        assert document["users"][0]["password_hash"]

        # New v2 schema columns are part of the payload.
        assert document["media"]
        media = document["media"][0]
        assert "source_sha1" in media
        assert "derivative_set" in media
        assert "avif_quality" not in media
        assert "ready_hash" not in media
        assert document["photos"][0]["hide_download_link"] in (0, 1)
        assert "allow_download" not in document["photos"][0]
        assert "media_derivatives" in document

        # Retired features never reappear.
        assert "comments" not in document


class TestImportRoundtrip:
    def test_restore_replaces_data_and_preserves_content(
        self, client: TestClient
    ) -> None:
        _prepare_site(client)
        before = _export(client)

        imported = _import(client, before, confirm=False, query="replace-all")
        assert imported.status_code == 200, imported.text
        result = imported.json()
        assert result["ok"] is True
        assert result["imported"] == {**_counts(before), "settings": 5}
        # The locally stored upload is still present after the database swap.
        assert result["missing_media_files"] == []

        # Sessions are replaced with the users table; log in with the imported
        # password hash.
        _login(client)
        after = _export(client)

        assert _counts(after) == _counts(before)
        assert _canonical(after) == _canonical(before)
        # Key content survives the round trip.
        post = next(item for item in after["posts"] if item["type"] == "post")
        assert post["title"] == "备份文章"
        assert post["content_md"].startswith("## 小标题")
        assert after["settings"]["appearance"]["accent"] == "#112233"
        assert {term["name"] for term in after["taxonomy_terms"]} == {"随笔", "日志"}

        # A second import is idempotent.
        second = _import(client, after)
        assert second.status_code == 200, second.text
        _login(client)
        final = _export(client)
        assert _counts(final) == _counts(before)
        assert _canonical(final) == _canonical(before)

    def test_confirm_query_parameter_is_accepted(self, client: TestClient) -> None:
        _prepare_site(client)
        document = _export(client)
        response = _import(client, document, confirm=False, query="replace-all")
        assert response.status_code == 200, response.text

    def test_autoincrement_continues_after_restore(self, client: TestClient) -> None:
        _prepare_site(client)
        document = _export(client)
        response = _import(client, document)
        assert response.status_code == 200, response.text
        _login(client)

        new_post = client.post(
            "/api/admin/posts",
            json={"title": "恢复后新文章", "content_md": "", "status": "draft"},
            headers=admin_headers(),
        )
        assert new_post.status_code == 201, new_post.text
        highest = max(post["id"] for post in document["posts"])
        assert new_post.json()["id"] == highest + 1


class TestImportValidation:
    def _reject(self, client: TestClient, payload: Any, code: str) -> None:
        assert payload.status_code in {409, 422}, payload.text
        body = payload.json()
        assert body["error"]["code"] == code, body
        assert body["error"]["message"]

    def test_rejects_2x_version(self, client: TestClient) -> None:
        _prepare_site(client)
        document = _export(client)
        document["version"] = 2
        self._reject(client, _import(client, document), "import.version_unsupported")

    def test_rejects_unknown_format(self, client: TestClient) -> None:
        _prepare_site(client)
        document = _export(client)
        document["format"] = "mztlab-old-export"
        self._reject(client, _import(client, document), "import.format_unsupported")

    def test_requires_destructive_confirmation(self, client: TestClient) -> None:
        _prepare_site(client)
        document = _export(client)
        self._reject(client, _import(client, document, confirm=False), "import.confirm_required")

    def test_rejects_broken_references_before_touching_data(
        self, client: TestClient
    ) -> None:
        _prepare_site(client)
        before = _export(client)
        document = copy.deepcopy(before)
        document["posts"][0]["owner_id"] = 999_999
        response = _import(client, document)
        self._reject(client, response, "import.invalid_reference")

        # Nothing was deleted: the same user session still sees the same site.
        after = _export(client)
        assert _counts(after) == _counts(before)


class TestMissingMedia:
    def test_missing_media_files_are_reported_not_fatal(
        self, client: TestClient
    ) -> None:
        setup_site(client)
        missing = _seed_media(client, with_file=False)
        document = _export(client)

        response = _import(client, document)
        assert response.status_code == 200, response.text
        body = response.json()
        # The JSON carries no binaries; a missing file is a warning, not a 500.
        assert missing["filename"] in body["missing_media_files"]

        _login(client)
        after = _export(client)
        assert any(
            media["filename"] == missing["filename"] for media in after["media"]
        )

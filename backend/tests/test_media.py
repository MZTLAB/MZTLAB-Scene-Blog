"""Media library: upload policy, serialization, PATCH semantics, streamed upload.

The HTTP tests exercise the real FastAPI stack with a temporary SQLite database
and an isolated upload/cache directory, so the streaming path (temp file →
validation → atomic move → media row + prewarm job) is covered end to end.
"""

from __future__ import annotations

import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import storage as storage_module
from app.db import db
from app.routes import media as media_module
from app.routes.media import (
    AUDIO_EXTENSIONS,
    FILE_FORMATS,
    _any_file_format,
    _audio_format,
    _file_format,
    _media_patch_columns,
    _serialize,
    _upload_policy,
)
from app.schemas import MediaAltIn
from app.settings import Settings
from tests.conftest import admin_headers, setup_site


def _settings(**upload_overrides: object) -> Settings:
    settings = Settings()
    for key, value in upload_overrides.items():
        setattr(settings.upload, key, value)
    return settings


def _png_bytes(size: tuple[int, int] = (8, 6), color: tuple[int, int, int] = (12, 34, 56)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _media_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 7,
        "filename": "2026/05/a.jpg",
        "original_name": "a.jpg",
        "mime": "image/jpeg",
        "size": 1234,
        "width": 800,
        "height": 600,
        "alt": "",
        "exif": "",
        "source_sha1": "",
        "derivative_set": "",
        "placeholder": "",
        "owner_id": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    row.update(overrides)
    return row


class MediaSerializeTests:
    """3.0.0 payload: `image` metadata only, no per-image quality fields."""

    def test_owner_comes_from_owner_id_only(self) -> None:
        item = _serialize(_media_row(), Settings())
        assert item["owner"]["id"] == 1
        assert item["owner"]["name"] == "未知成员"
        assert item["kind"] == "image"
        assert item["url"] == "/media/2026/05/a.jpg"
        # Internal token inputs never leak through the admin API.
        assert "source_sha1" not in item
        assert "derivative_set" not in item
        for retired in ("avif_quality", "avif_quality_auto", "ready_hash", "uploaded_by"):
            assert retired not in item

    def test_image_payload_reports_not_ready_before_prewarm(self) -> None:
        item = _serialize(_media_row(), Settings())
        image = item["image"]
        assert image is not None
        assert image["ready"] is False
        assert image["width"] == 800
        assert image["s"] == 720
        assert image["l"] == 800
        assert image["base"] == "/media/_v/7"
        assert image["formats"] == []

    def test_audio_and_file_rows_have_no_image_payload(self) -> None:
        audio = _serialize(_media_row(mime="audio/mpeg"), Settings())
        assert audio["kind"] == "audio"
        assert audio["image"] is None
        document = _serialize(_media_row(mime="application/pdf"), Settings())
        assert document["kind"] == "file"


class MediaPatchTests:
    """PATCH semantics: omit = keep. AVIF quality no longer exists (BC-34)."""

    def test_omitted_fields_are_not_written(self) -> None:
        assert _media_patch_columns(_media_row(), MediaAltIn()) == {}

    def test_provided_alt_only_changes_alt(self) -> None:
        columns = _media_patch_columns(_media_row(), MediaAltIn(alt="new"))
        assert columns == {"alt": "new"}

    def test_retired_quality_fields_are_ignored(self) -> None:
        payload = MediaAltIn.model_validate({"avif_quality": 60})
        assert _media_patch_columns(_media_row(), payload) == {}

    def test_audio_rows_accept_alt(self) -> None:
        payload = MediaAltIn(alt="声音")
        assert _media_patch_columns(_media_row(mime="audio/mpeg"), payload) == {"alt": "声音"}


class UploadPolicyTests:
    def test_policy_reads_typed_upload_settings(self) -> None:
        max_bytes, images, audio, files = _upload_policy(
            _settings(
                max_mb=5,
                image_formats=["png"],
                audio_formats=["mp3"],
                file_formats=["pdf"],
            )
        )
        assert max_bytes == 5 * 1024 * 1024
        assert set(images) == {"png"}
        assert set(audio) == {"mp3"}
        assert set(files) == {"pdf"}

    def test_empty_image_or_audio_selection_falls_back_to_the_catalog(self) -> None:
        _, images, audio, files = _upload_policy(
            _settings(image_formats=[], audio_formats=[], file_formats=[])
        )
        assert "jpg" in images
        assert "mp3" in audio
        assert files == {}

    def test_max_mb_is_clamped_to_the_technical_ceiling(self) -> None:
        max_bytes, _, _, _ = _upload_policy(_settings(max_mb=10_000))
        assert max_bytes == 200 * 1024 * 1024


class UploadFormatTests:
    def test_pdf_requires_magic_bytes(self) -> None:
        allowed = {"pdf": FILE_FORMATS["pdf"]}
        assert _file_format(b"%PDF-1.7\n...", "report.pdf", allowed) is not None
        assert _file_format(b"<html>hi</html>", "report.pdf", allowed) is None

    def test_ooxml_and_zip_require_zip_container(self) -> None:
        allowed = {"docx": FILE_FORMATS["docx"], "zip": FILE_FORMATS["zip"]}
        assert _file_format(b"PK\x03\x04rest", "notes.docx", allowed) is not None
        assert _file_format(b"not a zip", "notes.docx", allowed) is None

    def test_only_enabled_extensions_are_accepted(self) -> None:
        allowed = {"txt": FILE_FORMATS["txt"]}
        assert _file_format(b"hello", "notes.txt", allowed) is not None
        assert _file_format(b"hello", "notes.md", allowed) is None

    def test_dangerous_formats_are_not_in_catalog(self) -> None:
        for extension in ("html", "htm", "svg", "js", "mjs", "php", "exe"):
            assert extension not in FILE_FORMATS

    def test_audio_extension_must_be_enabled(self) -> None:
        allowed = {"mp3": AUDIO_EXTENSIONS["mp3"]}
        mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x00"
        assert _audio_format(mp3, "track.mp3", allowed) is not None
        assert _audio_format(mp3, "track.wav", allowed) is None

    def test_admin_any_file_keeps_safe_extension_and_mime(self) -> None:
        extension, mime = _any_file_format("model.glb")
        assert extension == "glb"
        assert mime
        extension, mime = _any_file_format("notes.weird type")
        assert " " not in extension
        assert "/" not in extension
        assert mime == "application/octet-stream"
        extension, mime = _any_file_format("no-extension")
        assert extension == "bin"
        assert mime == "application/octet-stream"


# ---------------------------------------------------------------------------
# Streamed upload (HTTP integration)
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_uploads(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the upload/cache directories (and the storage cache) at tmp_path."""
    upload_dir = tmp_path / "uploads"
    cache_dir = tmp_path / "cache"
    upload_dir.mkdir()
    cache_dir.mkdir()
    monkeypatch.setattr(media_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(storage_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(storage_module, "IMAGE_CACHE_DIR", cache_dir)
    storage_module.reset_storage()
    yield upload_dir
    storage_module.reset_storage()


def _leftover_temp_files(upload_dir) -> list:
    return [path for path in upload_dir.rglob("*") if path.suffix == ".tmp"]


def test_upload_streams_to_disk_and_stores_sha1(
    client: TestClient, isolated_uploads
) -> None:
    setup_site(client)
    data = _png_bytes()
    response = client.post(
        "/api/admin/media",
        files={"file": ("tiny.png", data, "image/png")},
        data={"alt": "一颗像素"},
        headers=admin_headers(),
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["kind"] == "image"
    assert item["alt"] == "一颗像素"
    assert item["image"] is not None
    assert item["image"]["ready"] is False
    assert "avif_quality" not in item
    assert item["placeholder"].startswith("#")

    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (item["id"],)).fetchone()
        job = conn.execute(
            "SELECT * FROM jobs WHERE kind = 'prewarm' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["source_sha1"] == hashlib.sha1(data).hexdigest()
    assert row["derivative_set"] == ""
    assert job is not None
    assert job["payload"] == '{{"media_id":{}}}'.format(item["id"])

    # The uploaded bytes live under uploads/YYYY/MM/{uuid}.png, no temp file left.
    stored = isolated_uploads / row["filename"]
    assert stored.is_file()
    assert stored.read_bytes() == data
    assert _leftover_temp_files(isolated_uploads) == []


def test_upload_rejects_oversized_body_and_cleans_up(
    client: TestClient, isolated_uploads, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_site(client)
    # Administrators bypass the settings policy but not the technical ceiling;
    # shrink that ceiling so the streaming abort is cheap to exercise.
    monkeypatch.setattr(media_module, "ADMIN_MAX_UPLOAD_BYTES", 1024)
    data = _png_bytes(size=(400, 400))
    assert len(data) > 1024
    response = client.post(
        "/api/admin/media",
        files={"file": ("big.png", data, "image/png")},
        headers=admin_headers(),
    )
    assert response.status_code == 413
    assert "1MB" in response.json()["error"]["message"]
    assert _leftover_temp_files(isolated_uploads) == []
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0


def test_upload_audio_does_not_enqueue_prewarm(
    client: TestClient, isolated_uploads
) -> None:
    setup_site(client)
    response = client.post(
        "/api/admin/media",
        files={"file": ("track.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x00", "audio/mpeg")},
        headers=admin_headers(),
    )
    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "audio"
    with db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE kind = 'prewarm'"
        ).fetchone()[0]
    assert count == 0


def test_upload_rejects_unauthenticated_request(client: TestClient) -> None:
    setup_site(client)
    client.post("/api/auth/logout")
    response = client.post(
        "/api/admin/media",
        files={"file": ("tiny.png", _png_bytes(), "image/png")},
    )
    # The CSRF marker is checked before authentication on unsafe admin routes.
    assert response.status_code == 403


def test_media_patch_updates_alt_only(client: TestClient, isolated_uploads) -> None:
    setup_site(client)
    created = client.post(
        "/api/admin/media",
        files={"file": ("tiny.png", _png_bytes(), "image/png")},
        headers=admin_headers(),
    ).json()
    response = client.patch(
        f"/api/admin/media/{created['id']}",
        json={"alt": "新说明"},
        headers=admin_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["alt"] == "新说明"
    # The retired fields are simply ignored, not rejected.
    again = client.patch(
        f"/api/admin/media/{created['id']}",
        json={"avif_quality": 60},
        headers=admin_headers(),
    )
    assert again.status_code == 200
    assert "avif_quality" not in again.json()


def test_optimize_enqueues_reencode_job(client: TestClient, isolated_uploads) -> None:
    setup_site(client)
    created = client.post(
        "/api/admin/media",
        files={"file": ("tiny.png", _png_bytes(), "image/png")},
        headers=admin_headers(),
    ).json()
    response = client.post(
        f"/api/admin/media/{created['id']}/optimize", headers=admin_headers()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    with db() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (body["job_id"],)
        ).fetchone()
    assert job["kind"] == "reencode"
    assert job["status"] == "queued"

    all_response = client.post("/api/admin/media/optimize-all", headers=admin_headers())
    assert all_response.status_code == 200
    assert all_response.json()["ok"] is True


def test_removed_media_and_storage_status_routes_are_gone(client: TestClient) -> None:
    setup_site(client)
    # The old in-memory progress endpoints were replaced by /api/admin/jobs.
    assert client.get("/api/admin/media/optimize-status", headers=admin_headers()).status_code in {
        404,
        405,
        422,
    }
    assert client.get("/api/admin/storage/sync-status", headers=admin_headers()).status_code in {
        404,
        405,
        422,
    }

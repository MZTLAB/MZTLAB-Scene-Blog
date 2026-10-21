"""Gallery admin + media integration on the 3.0.0 schema.

Covers the `hide_download_link` rename (BC-20) and the media→photo reference
path: an uploaded image becomes a gallery photo whose payload carries the
read-only `image` metadata from the image pipeline.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import storage as storage_module
from app.db import db
from app.routes import media as media_module
from tests.conftest import admin_headers, setup_site


def _png_bytes(size: tuple[int, int] = (12, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (40, 80, 120)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture()
def isolated_uploads(tmp_path, monkeypatch: pytest.MonkeyPatch):
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


def _upload_image(client: TestClient) -> dict:
    response = client.post(
        "/api/admin/media",
        files={"file": ("scene.png", _png_bytes(), "image/png")},
        headers=admin_headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_gallery(client: TestClient) -> dict:
    response = client.post(
        "/api/admin/galleries",
        json={"title": "夜色", "description": "测试相册", "status": "published"},
        headers=admin_headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_then_add_to_gallery_keeps_new_photo_shape(
    client: TestClient, isolated_uploads
) -> None:
    setup_site(client)
    media = _upload_image(client)
    gallery = _create_gallery(client)

    added = client.post(
        f"/api/admin/galleries/{gallery['id']}/photos",
        json={"media_ids": [media["id"]]},
        headers=admin_headers(),
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["ok"] is True
    assert len(body["added"]) == 1
    photos = body["gallery"]["photos"]
    assert len(photos) == 1
    photo = photos[0]
    assert photo["media_id"] == media["id"]
    assert photo["hide_download_link"] is False
    assert photo["download_url"].endswith("?download=1")
    assert "allow_download" not in photo
    # The image pipeline metadata is read-only and not ready before prewarm.
    assert photo["image"] is not None
    assert photo["image"]["ready"] is False
    assert photo["width"] == 12
    assert photo["height"] == 8

    # The database column really is `hide_download_link` (0 = show the link).
    with db() as conn:
        row = conn.execute(
            "SELECT hide_download_link FROM photos WHERE id = ?", (body["added"][0],)
        ).fetchone()
    assert int(row["hide_download_link"]) == 0


def test_patch_hide_download_link_toggles_the_affordance(
    client: TestClient, isolated_uploads
) -> None:
    setup_site(client)
    media = _upload_image(client)
    gallery = _create_gallery(client)
    added = client.post(
        f"/api/admin/galleries/{gallery['id']}/photos",
        json={"media_ids": [media["id"]]},
        headers=admin_headers(),
    ).json()
    photo_id = added["added"][0]

    hidden = client.patch(
        f"/api/admin/photos/{photo_id}",
        json={"hide_download_link": True},
        headers=admin_headers(),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["hide_download_link"] is True
    assert hidden.json()["download_url"] == ""

    # Explicit null means "show the download link again" -> column 0.
    shown = client.patch(
        f"/api/admin/photos/{photo_id}",
        json={"hide_download_link": None},
        headers=admin_headers(),
    )
    assert shown.status_code == 200, shown.text
    assert shown.json()["hide_download_link"] is False
    with db() as conn:
        row = conn.execute(
            "SELECT hide_download_link FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()
    assert int(row["hide_download_link"]) == 0


def test_create_photo_directly_with_hide_download_link(
    client: TestClient, isolated_uploads
) -> None:
    setup_site(client)
    media = _upload_image(client)
    created = client.post(
        "/api/admin/photos",
        json={"media_id": media["id"], "hide_download_link": True, "title": "独立照片"},
        headers=admin_headers(),
    )
    assert created.status_code == 201, created.text
    photo = created.json()
    assert photo["hide_download_link"] is True
    assert photo["title"] == "独立照片"
    assert photo["gallery_id"] is None
    with db() as conn:
        row = conn.execute(
            "SELECT hide_download_link FROM photos WHERE id = ?", (photo["id"],)
        ).fetchone()
    assert int(row["hide_download_link"]) == 1


def test_gallery_detail_and_photo_listing_use_the_new_column(
    client: TestClient, isolated_uploads
) -> None:
    setup_site(client)
    media = _upload_image(client)
    gallery = _create_gallery(client)
    client.post(
        f"/api/admin/galleries/{gallery['id']}/photos",
        json={"media_ids": [media["id"]]},
        headers=admin_headers(),
    )
    detail = client.get(
        f"/api/admin/galleries/{gallery['id']}", headers=admin_headers()
    )
    assert detail.status_code == 200, detail.text
    item = detail.json()
    assert item["photo_count"] == 1
    assert item["cover"] is not None
    assert item["cover"]["hide_download_link"] is False
    assert item["owner_id"] is not None

    listing = client.get(
        "/api/admin/photos", params={"gallery_id": gallery["id"]}, headers=admin_headers()
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["hide_download_link"] is False


def test_batch_patch_columns_semantics() -> None:
    """Unit-level check of the PATCH mapping (see tests/test_galleries.py)."""
    from app.routes.gallery_admin import _photo_patch_columns
    from app.schemas import PhotoUpdateIn

    assert _photo_patch_columns(PhotoUpdateIn()) == {}
    assert _photo_patch_columns(PhotoUpdateIn.model_validate({"title": "x"})) == {"title": "x"}
    assert _photo_patch_columns(
        PhotoUpdateIn.model_validate({"hide_download_link": True})
    ) == {"hide_download_link": 1}
    assert _photo_patch_columns(
        PhotoUpdateIn.model_validate({"hide_download_link": None})
    ) == {"hide_download_link": 0}

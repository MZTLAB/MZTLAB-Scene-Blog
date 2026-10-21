"""Public media serving: originals + artifact-token derivatives through storage.

3.0.0 routes read through `get_storage().size()` + `.stream()` only; these tests
use a fake backend with no filesystem methods at all, so any regression back to
`local_path()`/FileResponse fails here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import db
from app.routes import media_serve
from app.routes.media_serve import _content_disposition
from app.storage import StorageMissing
from tests.conftest import setup_site


class FakeStorage:
    """A storage backend exposing only the narrowed read interface."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.streamed: list[str] = []

    def size(self, key: str) -> int:
        if key not in self.objects:
            raise StorageMissing(key)
        return len(self.objects[key])

    def stream(self, key: str):
        if key not in self.objects:
            raise StorageMissing(key)
        self.streamed.append(key)

        def chunks():
            data = self.objects[key]
            yield data[:4]
            yield data[4:]

        return chunks()


@pytest.fixture()
def fake_storage(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    backend = FakeStorage(
        {
            "2026/05/a.jpg": b"original-bytes",
            "2026/05/active.svg": b"<svg/>",
            "_derived/7/abc123/tile/720.avif": b"avif-bytes",
        }
    )
    monkeypatch.setattr(media_serve, "get_storage", lambda: backend)
    return backend


def _insert_media(conn, filename: str = "2026/05/a.jpg") -> int:
    cursor = conn.execute(
        """INSERT INTO media(filename, original_name, mime, size, width, height,
                             alt, owner_id, created_at)
           VALUES (?, 'a.jpg', 'image/jpeg', 14, 800, 600, '', 1, '2026-01-01T00:00:00Z')""",
        (filename,),
    )
    return int(cursor.lastrowid or 0)


def _insert_derivative(conn, media_id: int, token: str, key: str, scene: str = "tile") -> None:
    conn.execute(
        """INSERT INTO media_derivatives(media_id, token, pipeline_version, scene,
                                         width, format, quality, height, size, key, created_at)
           VALUES (?, ?, 4, ?, 720, 'avif', 50, 540, 10, ?, '2026-01-01T00:00:00Z')""",
        (media_id, token, scene, key),
    )


class ContentDispositionTests:
    def test_keeps_unicode_filename_and_ascii_fallback(self):
        header = _content_disposition("夜色 01.jpg")
        assert header.startswith("attachment;")
        assert 'filename="' in header
        assert "filename*=UTF-8''" in header
        assert "\r" not in header
        assert "\n" not in header

    def test_strips_header_injection_characters(self):
        header = _content_disposition('evil"\r\nX-Test: 1.jpg')
        assert "\r" not in header
        assert "\n" not in header
        fallback = header.split('filename="', 1)[1].split('"', 1)[0]
        assert '"' not in fallback

    def test_empty_name_has_a_fallback(self):
        assert 'filename="download"' in _content_disposition("")


def test_original_is_streamed_through_storage(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    response = client.get("/media/2026/05/a.jpg")
    assert response.status_code == 200
    assert response.content == b"original-bytes"
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.headers["content-length"] == "14"
    assert fake_storage.streamed == ["2026/05/a.jpg"]


def test_missing_original_is_404(client: TestClient, fake_storage: FakeStorage) -> None:
    assert client.get("/media/2026/05/missing.jpg").status_code == 404


def test_active_media_is_an_attachment_with_sandbox_csp(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    response = client.get("/media/2026/05/active.svg")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in response.headers["content-security-policy"]


def test_derivative_serves_the_existing_row_with_immutable_cache(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    setup_site(client)
    with db() as conn:
        media_id = _insert_media(conn)
        _insert_derivative(conn, media_id, "abc123", "_derived/7/abc123/tile/720.avif")
    response = client.get(f"/media/_v/{media_id}/abc123/tile/720.avif")
    assert response.status_code == 200
    assert response.content == b"avif-bytes"
    assert response.headers["cache-control"] == "public, max-age=31536000"


def test_derivative_without_row_is_404_and_never_encodes(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    setup_site(client)
    with db() as conn:
        media_id = _insert_media(conn)
    assert client.get(f"/media/_v/{media_id}/zzz/tile/720.avif").status_code == 404
    # Unknown scene / malformed name are 404 too.
    assert client.get(f"/media/_v/{media_id}/zzz/nonsense/720.avif").status_code == 404
    assert client.get(f"/media/_v/{media_id}/zzz/tile/720.gif").status_code == 404
    assert fake_storage.streamed == []


def test_derivative_row_with_missing_object_is_404(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    setup_site(client)
    with db() as conn:
        media_id = _insert_media(conn)
        _insert_derivative(conn, media_id, "gone", "_derived/7/gone/tile/720.avif")
    assert client.get(f"/media/_v/{media_id}/gone/tile/720.avif").status_code == 404


def test_path_traversal_on_originals_is_rejected(
    client: TestClient, fake_storage: FakeStorage
) -> None:
    for path in ("/media/..%2F..%2Fetc%2Fpasswd", "/media/%2E%2E/secret"):
        assert client.get(path).status_code in {400, 404}

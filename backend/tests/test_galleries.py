from __future__ import annotations

import sqlite3
import unittest

from app.errors import ApiError
from app.galleries import photo_dict
from app.posts import public_url
from app.routes.gallery_admin import _apply_columns, _photo_patch_columns
from app.schemas import PhotoUpdateIn
from app.services.authz import authorize, authorize_photo
from app.settings import Settings


class GalleryShapeTests(unittest.TestCase):
    def test_photo_dict_builds_urls_and_aspect(self) -> None:
        item = photo_dict(
            {
                "id": 4,
                "gallery_id": 2,
                "gallery_slug": "nocturne",
                "gallery_title": "夜色",
                "media_id": 9,
                "filename": "seed/nocturne-01.jpg",
                "title": "夜色 01",
                "caption": "",
                "width": 1600,
                "height": 800,
                "featured": 1,
                "status": "published",
                "sort_order": 10,
                "created_at": "2026-01-01T00:00:00Z",
            },
            Settings(),
        )
        self.assertEqual(item["url"], "/media/seed/nocturne-01.jpg")
        self.assertEqual(item["aspect"], 2.0)
        self.assertEqual(item["alt"], "夜色 01")
        self.assertTrue(item["featured"])
        self.assertEqual(item["gallery"]["url"], "/galleries/nocturne")
        # Original download is allowed by default and uses an attachment URL.
        self.assertTrue(item["allow_download"])
        self.assertEqual(item["download_url"], "/media/seed/nocturne-01.jpg?download=1")
        self.assertEqual(item["download_name"], "nocturne-01.jpg")

    def test_photo_can_disable_original_download(self) -> None:
        item = photo_dict(
            {
                "id": 11,
                "filename": "scene/two.jpg",
                "width": 1200,
                "height": 800,
                "allow_download": 0,
            },
            Settings(),
        )
        self.assertFalse(item["allow_download"])
        self.assertEqual(item["download_url"], "")

    def test_loose_photo_has_no_gallery(self) -> None:
        item = photo_dict({"id": 1, "filename": "a.jpg", "width": 0, "height": 0}, Settings())
        self.assertIsNone(item["gallery"])
        self.assertEqual(item["aspect"], 1.5)


class UrlShapeTests(unittest.TestCase):
    def test_content_types_get_their_own_section(self) -> None:
        self.assertEqual(public_url({"type": "post", "slug": "hello"}), "/posts/hello")
        self.assertEqual(public_url({"type": "page", "slug": "about"}), "/about")
        # Projects are a first-class content type again (Index theme).
        self.assertEqual(public_url({"type": "project", "slug": "form-01"}), "/projects/form-01")

    def test_photo_exposes_technical_exif(self) -> None:
        item = photo_dict(
            {
                "id": 7,
                "gallery_id": 2,
                "gallery_slug": "scene",
                "gallery_title": "Scene",
                "filename": "scene/one.jpg",
                "title": "One",
                "width": 6240,
                "height": 4160,
                "media_exif": '{"camera":"X-T30","focal_length":"45.1mm",'
                '"focal_length_35mm":68,"aperture":"f/5.6","exposure":"1/4000s",'
                '"iso":400,"taken_at":"2026-07-12"}',
            },
            Settings(),
        )
        self.assertEqual(item["focal_length"], "45.1mm")
        self.assertEqual(item["focal_length_35mm"], 68)
        self.assertEqual(item["aperture"], "f/5.6")
        self.assertEqual(item["iso"], 400)
        self.assertEqual(item["exif"]["camera"], "X-T30")


class PhotoPatchSemanticsTests(unittest.TestCase):
    """PATCH: omitted fields keep their value, explicit null clears."""

    def test_omitted_fields_are_not_written(self) -> None:
        columns = _photo_patch_columns(PhotoUpdateIn.model_validate({"title": "新标题"}))
        self.assertEqual(columns, {"title": "新标题"})

    def test_explicit_null_removes_photo_from_gallery(self) -> None:
        columns = _photo_patch_columns(PhotoUpdateIn.model_validate({"gallery_id": None}))
        self.assertIn("gallery_id", columns)
        self.assertIsNone(columns["gallery_id"])

    def test_explicit_null_clears_exif_visibility_and_download(self) -> None:
        columns = _photo_patch_columns(
            PhotoUpdateIn.model_validate(
                {"exif_fields": None, "allow_download": None, "sort_order": None}
            )
        )
        self.assertEqual(columns["exif_fields"], "")
        self.assertEqual(columns["allow_download"], 1)
        self.assertEqual(columns["sort_order"], 0)

    def test_partial_update_only_touches_the_provided_column(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "CREATE TABLE photos(id INTEGER PRIMARY KEY, gallery_id INTEGER, "
                "title TEXT, caption TEXT)"
            )
            conn.execute(
                "INSERT INTO photos(id, gallery_id, title, caption) VALUES (1, 2, 'a', 'b')"
            )
            _apply_columns(conn, "photos", 1, {"title": "changed"})
            row = conn.execute("SELECT * FROM photos WHERE id = 1").fetchone()
            self.assertEqual(row["title"], "changed")
            self.assertEqual(row["gallery_id"], 2)
            self.assertEqual(row["caption"], "b")
            _apply_columns(conn, "photos", 1, {"gallery_id": None})
            row = conn.execute("SELECT * FROM photos WHERE id = 1").fetchone()
            self.assertIsNone(row["gallery_id"])
            self.assertEqual(row["title"], "changed")
        finally:
            conn.close()


def _user(user_id: int, permissions: list[str]) -> dict[str, object]:
    return {"id": user_id, "permissions": permissions}


class AuthorizationTests(unittest.TestCase):
    """Galleries/photos use the single authz entry point with owner_id."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE galleries(id INTEGER PRIMARY KEY, owner_id INTEGER)")
        self.conn.execute("CREATE TABLE photos(id INTEGER PRIMARY KEY, gallery_id INTEGER)")
        self.conn.execute("INSERT INTO galleries(id, owner_id) VALUES (1, 10)")
        self.conn.execute("INSERT INTO photos(id, gallery_id) VALUES (100, 1)")
        self.conn.execute("INSERT INTO photos(id, gallery_id) VALUES (101, NULL)")

    def tearDown(self) -> None:
        self.conn.close()

    def _gallery(self) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM galleries WHERE id = 1").fetchone()

    def _photo(self, photo_id: int) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()

    def test_owner_can_write_own_gallery(self) -> None:
        authorize(_user(10, []), self._gallery(), "write")

    def test_non_owner_is_forbidden(self) -> None:
        with self.assertRaises(ApiError) as raised:
            authorize(_user(11, []), self._gallery(), "write")
        self.assertEqual(raised.exception.status_code, 403)

    def test_content_others_bypasses_ownership(self) -> None:
        authorize(_user(11, ["content.others"]), self._gallery(), "write")

    def test_photo_is_authorized_through_its_gallery(self) -> None:
        row = self._photo(100)
        authorize_photo(_user(10, []), self.conn, row, "write")
        with self.assertRaises(ApiError) as raised:
            authorize_photo(_user(11, []), self.conn, row, "write")
        self.assertEqual(raised.exception.status_code, 403)

    def test_loose_photo_has_no_owner_and_content_others_wins(self) -> None:
        row = self._photo(101)
        with self.assertRaises(ApiError):
            authorize_photo(_user(10, []), self.conn, row, "write")
        authorize_photo(_user(11, ["content.others"]), self.conn, row, "write")


if __name__ == "__main__":
    unittest.main()

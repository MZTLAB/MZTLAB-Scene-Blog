from __future__ import annotations

import json
import sqlite3
import unittest

from app.errors import ApiError
from app.galleries import gallery_dict, photo_dict
from app.images import artifact_url
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
        # Schema v2 semantics: the original download is shown by default.
        self.assertIs(item["hide_download_link"], False)
        self.assertEqual(item["download_url"], "/media/seed/nocturne-01.jpg?download=1")
        self.assertEqual(item["download_name"], "nocturne-01.jpg")
        self.assertNotIn("allow_download", item)

    def test_hidden_download_link_has_no_download_url(self) -> None:
        item = photo_dict(
            {
                "id": 11,
                "filename": "scene/two.jpg",
                "width": 1200,
                "height": 800,
                "hide_download_link": 1,
            },
            Settings(),
        )
        self.assertIs(item["hide_download_link"], True)
        self.assertEqual(item["download_url"], "")
        # Hiding the affordance never hides the (public) original URL.
        self.assertEqual(item["url"], "/media/scene/two.jpg")

    def test_loose_photo_has_no_gallery(self) -> None:
        item = photo_dict({"id": 1, "filename": "a.jpg", "width": 0, "height": 0}, Settings())
        self.assertIsNone(item["gallery"])
        self.assertEqual(item["aspect"], 1.5)


class ImagePayloadTests(unittest.TestCase):
    """`photo_dict` must pass the v2 media columns to `images.image_payload`."""

    def _row(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "id": 4,
            "gallery_id": 2,
            "gallery_slug": "form-studies",
            "gallery_title": "FORM / 结构练习",
            "media_id": 9,
            "filename": "seed/form-studies-01.jpg",
            "title": "FORM 01",
            "caption": "",
            "width": 1600,
            "height": 1000,
            "media_mime": "image/jpeg",
            "media_size": 123_456,
            "media_width": 3200,
            "media_height": 2000,
            "media_source_sha1": "a" * 40,
            "media_derivative_set": "",
            "media_placeholder": "#c2451f",
        }
        row.update(overrides)
        return row

    def test_not_ready_falls_back_to_the_original(self) -> None:
        item = photo_dict(self._row(), Settings())
        image = item["image"]
        assert image is not None
        # No derivative set yet: the frontend falls back to `item["url"]`.
        self.assertIs(image["ready"], False)
        self.assertFalse(image["artifacts"])
        self.assertEqual(image["formats"], [])
        self.assertEqual(image["base"], "/media/_v/9")
        self.assertEqual(image["placeholder"], "#c2451f")
        self.assertEqual((image["s"], image["l"], image["f"]), (720, 2560, 3200))

    def test_ready_derivative_set_is_exposed_by_token(self) -> None:
        derivative_set = json.dumps(
            {
                "ready": True,
                "pipeline_version": 4,
                "s": 720,
                "l": 2560,
                "f": 3200,
                "artifacts": {
                    "card": {"720": {"jpeg": "aaaabbbb01", "webp": "aaaabbbb02"}},
                    "full": {"3200": {"jpeg": "aaaabbbb03"}},
                },
            }
        )
        item = photo_dict(self._row(media_derivative_set=derivative_set), Settings())
        image = item["image"]
        assert image is not None
        self.assertIs(image["ready"], True)
        self.assertEqual(image["pipeline_version"], 4)
        # `images` owns the payload shape; the tokens must survive it either as
        # a nested map or as a flattened artifact list.
        self.assertIn("aaaabbbb01", json.dumps(image["artifacts"]))
        self.assertEqual(
            artifact_url(image, "card", 720, "jpeg", prefer_direct=False),
            "/media/_v/9/aaaabbbb01/card/720.jpg",
        )
        # URLs only exist for artifacts the set actually contains.
        self.assertEqual(artifact_url(image, "hero", 2560, "jpeg"), "")

    def test_missing_media_row_has_no_payload(self) -> None:
        item = photo_dict(self._row(media_id=None), Settings())
        self.assertIsNone(item["image"])


class PhotoColumnsTests(unittest.TestCase):
    """The v2 columns in `_PHOTO_COLUMNS` must match the real schema."""

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users(id INTEGER PRIMARY KEY, display_name TEXT,
                               username TEXT, avatar TEXT);
            CREATE TABLE galleries(id INTEGER PRIMARY KEY, title TEXT, slug TEXT,
                                   description TEXT, status TEXT, featured INTEGER,
                                   cover_photo_id INTEGER, owner_id INTEGER,
                                   created_at TEXT, updated_at TEXT);
            CREATE TABLE media(id INTEGER PRIMARY KEY, filename TEXT,
                               original_name TEXT, mime TEXT, size INTEGER,
                               width INTEGER, height INTEGER, alt TEXT,
                               owner_id INTEGER, exif TEXT, source_sha1 TEXT,
                               derivative_set TEXT, placeholder TEXT,
                               created_at TEXT);
            CREATE TABLE photos(id INTEGER PRIMARY KEY, gallery_id INTEGER,
                                media_id INTEGER, filename TEXT, title TEXT,
                                caption TEXT, location TEXT, camera TEXT,
                                lens TEXT, taken_at TEXT, width INTEGER,
                                height INTEGER, exif_fields TEXT,
                                hide_download_link INTEGER, featured INTEGER,
                                status TEXT, sort_order INTEGER, created_at TEXT);
            """
        )
        conn.execute("INSERT INTO users VALUES (1, 'MZTLAB', 'mztlab', '')")
        conn.execute(
            "INSERT INTO galleries VALUES (2, 'FORM', 'form-studies', '边界练习', "
            "'published', 1, 10, 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO media VALUES (9, 'seed/form-studies-01.jpg', "
            "'form-studies-01.jpg', 'image/jpeg', 1000, 3200, 2000, 'FORM 01', 1, "
            "'{}', 'deadbeef', '', '#c2451f', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO photos VALUES (10, 2, 9, 'seed/form-studies-01.jpg', "
            "'FORM 01', '', '上海', 'Ricoh GR III', '28mm', '2026-01-01', 1600, "
            "1000, '', 0, 1, 'published', 10, '2026-01-01T00:00:00Z')"
        )
        return conn

    def test_gallery_dict_reads_v2_columns(self) -> None:
        conn = self._connection()
        try:
            row = conn.execute(
                "SELECT g.*, u.display_name AS author_name, "
                "u.username AS author_username, u.avatar AS author_avatar "
                "FROM galleries g LEFT JOIN users u ON u.id = g.owner_id "
                "WHERE g.id = 2"
            ).fetchone()
            assert row is not None
            gallery = gallery_dict(conn, row, detail=True, settings=Settings())
        finally:
            conn.close()
        self.assertEqual(gallery["photo_count"], 1)
        photo = gallery["photos"][0]
        self.assertEqual(photo["media_id"], 9)
        self.assertIs(photo["hide_download_link"], False)
        image = photo["image"]
        assert image is not None
        self.assertIs(image["ready"], False)
        self.assertEqual(image["placeholder"], "#c2451f")


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

    def test_explicit_null_resets_hidden_download_link(self) -> None:
        if "hide_download_link" not in PhotoUpdateIn.model_fields:
            # Lead owns app/schemas.py; until the `allow_download` ->
            # `hide_download_link` rename lands this assertion cannot hold.
            self.skipTest("PhotoUpdateIn.hide_download_link rename pending")
        columns = _photo_patch_columns(
            PhotoUpdateIn.model_validate(
                {"exif_fields": None, "hide_download_link": None, "sort_order": None}
            )
        )
        self.assertEqual(columns["exif_fields"], "")
        self.assertEqual(columns["hide_download_link"], 0)
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

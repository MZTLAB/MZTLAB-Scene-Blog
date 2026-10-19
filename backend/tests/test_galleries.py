from __future__ import annotations

import unittest

from app.galleries import photo_dict
from app.posts import public_url


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
            }
        )
        self.assertEqual(item["url"], "/media/seed/nocturne-01.jpg")
        self.assertEqual(item["aspect"], 2.0)
        self.assertEqual(item["alt"], "夜色 01")
        self.assertTrue(item["featured"])
        self.assertEqual(item["gallery"]["url"], "/galleries/nocturne")

    def test_loose_photo_has_no_gallery(self) -> None:
        item = photo_dict({"id": 1, "filename": "a.jpg", "width": 0, "height": 0})
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
            }
        )
        self.assertEqual(item["focal_length"], "45.1mm")
        self.assertEqual(item["focal_length_35mm"], 68)
        self.assertEqual(item["aperture"], "f/5.6")
        self.assertEqual(item["iso"], 400)
        self.assertEqual(item["exif"]["camera"], "X-T30")


if __name__ == "__main__":
    unittest.main()

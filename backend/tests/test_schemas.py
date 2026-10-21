from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.avatars import clean_avatar_url
from app.schemas import PostIn, ProfileIn


class ProjectKindTests(unittest.TestCase):
    def test_presets_still_accepted(self) -> None:
        self.assertEqual(PostIn(title="x", project_kind="code").project_kind, "code")
        self.assertEqual(PostIn(title="x", project_kind="video").project_kind, "video")

    def test_custom_type_is_allowed(self) -> None:
        self.assertEqual(
            PostIn(title="x", project_kind="字体设计").project_kind,
            "字体设计",
        )
        self.assertEqual(
            PostIn(title="x", project_kind="motion / 3D").project_kind,
            "motion / 3D",
        )

    def test_type_is_normalised(self) -> None:
        payload = PostIn(title="x", project_kind="  字体   设计  ")
        self.assertEqual(payload.project_kind, "字体 设计")
        payload = PostIn(title="x", project_kind="a\x00b")
        self.assertEqual(payload.project_kind, "ab")
        self.assertEqual(PostIn(title="x").project_kind, "")

    def test_type_has_a_length_limit(self) -> None:
        with self.assertRaises(ValidationError):
            PostIn(title="x", project_kind="x" * 41)

    def test_author_transfer_target_must_be_positive(self) -> None:
        self.assertEqual(PostIn(title="x", author_id=3).author_id, 3)
        self.assertIsNone(PostIn(title="x").author_id)
        with self.assertRaises(ValidationError):
            PostIn(title="x", author_id=0)


class AvatarPolicyTests(unittest.TestCase):
    def _profile(self, avatar: str) -> ProfileIn:
        return ProfileIn(display_name="成员", avatar=avatar)

    def test_accepts_raster_image_links(self) -> None:
        for avatar in (
            "",
            "/media/2026/10/photo.jpg",
            "/media/_v/42/abcdef/full/2560.avif",
            "/media/2026/10/photo.png?download=1",
            "https://cdn.example.com/a/photo.PNG?width=256",
            "http://example.com/a.webp#avatar",
        ):
            self.assertEqual(self._profile(avatar).avatar, avatar)

    def test_rejects_active_or_non_image_files(self) -> None:
        for avatar in (
            "/media/2026/10/evil.svg",
            "https://cdn.example.com/evil.svg",
            "/media/2026/10/page.html",
            "/media/2026/10/report.pdf",
            "/media/2026/10/script.js",
            "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
            "data:image/png;base64,iVBORw0KGgo=",
            "javascript:alert(1)",
            "blob:https://example.com/abc",
            "//evil.example/a.jpg",
            "media/photo.jpg",
            "https://cdn.example.com/a.jpg/",
            "https://cdn.example.com/no-extension",
            'https://cdn.example.com/a.jpg" onerror="alert(1)',
            "https://cdn.example.com/a.jpg\n.jpg",
        ):
            with self.assertRaises(ValidationError, msg=avatar):
                self._profile(avatar)

    def test_legacy_values_are_dropped_on_output(self) -> None:
        self.assertEqual(clean_avatar_url("/media/x.png"), "/media/x.png")
        self.assertEqual(clean_avatar_url(""), "")
        self.assertEqual(clean_avatar_url(None), "")
        self.assertEqual(clean_avatar_url("/media/x.svg"), "")
        self.assertEqual(clean_avatar_url("javascript:alert(1)"), "")


if __name__ == "__main__":
    unittest.main()

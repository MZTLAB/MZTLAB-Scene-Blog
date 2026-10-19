from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.schemas import PostIn


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


if __name__ == "__main__":
    unittest.main()

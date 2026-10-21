"""Grouped settings: single default source, validation and PATCH merging."""

from __future__ import annotations

import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from app import db as db_module
from app.db import connect, init_db
from app.settings import (
    GROUPS,
    Settings,
    SettingsPatch,
    default_settings,
    invalidate_settings_cache,
    load_settings,
    load_settings_cached,
    public_settings,
    save_settings_patch,
)
from app.settings.models import (
    AppearanceSettings,
    CopySettings,
    SiteSettings,
    StorageSettings,
    UploadSettings,
)


class SettingsSnapshotTests(unittest.TestCase):
    def test_five_groups_are_the_only_storage_documents(self) -> None:
        self.assertEqual(GROUPS, ("site", "appearance", "copy", "upload", "advanced"))

    def test_defaults_come_from_one_model_set(self) -> None:
        settings = default_settings()
        self.assertIsInstance(settings, Settings)
        self.assertEqual(set(settings.model_dump()), set(GROUPS))
        # A fresh document is fully validated; no loose dicts.
        self.assertIsInstance(settings.site, SiteSettings)
        self.assertIsInstance(settings.appearance, AppearanceSettings)
        self.assertIsInstance(settings.copy, CopySettings)
        self.assertIsInstance(settings.upload, UploadSettings)
        self.assertIsInstance(settings.advanced.storage, StorageSettings)

    def test_removed_setting_keys_are_gone(self) -> None:
        flat = json.dumps(default_settings().model_dump(), ensure_ascii=False)
        for retired in (
            "comments_enabled",
            "comment_moderation",
            "copy_comments",
            "show_views",
            "view_count",
            "author_name",
            "author_bio",
            "author_avatar",
            "home_projects_title",
            "home_gallery_title",
            "home_section_title",
            "storage_s3_secret_key",
        ):
            self.assertNotIn(retired, flat)

    def test_public_projection_hides_internal_documents(self) -> None:
        public = default_settings().public_dump()
        self.assertEqual(set(public), {"site", "appearance", "copy"})
        self.assertNotIn("editor_manage_others", public["site"])
        self.assertNotIn("storage", json.dumps(public))
        self.assertEqual(public["copy"]["photos_title"], "影像")

    def test_defaults_are_self_consistent(self) -> None:
        settings = default_settings()
        self.assertEqual(settings.upload.image_formats[:3], ["jpg", "png", "webp"])
        self.assertEqual(settings.advanced.image.widths, [720, 2560])
        self.assertEqual(settings.appearance.accent, "#c2451f")
        self.assertEqual(settings.advanced.storage.backend, "local")


class SettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._old_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmp.name) / "settings.db"
        invalidate_settings_cache()
        init_db()

    def tearDown(self) -> None:
        db_module.DB_PATH = self._old_path
        invalidate_settings_cache()
        self._tmp.cleanup()

    def test_empty_database_starts_with_five_default_documents(self) -> None:
        settings = load_settings()
        self.assertEqual(settings.site.site_title, "MZTLAB")
        with closing(connect()) as conn:
            rows = conn.execute('SELECT "group" FROM settings').fetchall()
            self.assertEqual(len(rows), 5)

    def test_patch_merges_only_sent_fields(self) -> None:
        patch = SettingsPatch(
            site={"site_title": "新标题"},
            appearance={"accent": "#112233"},
            copy={"photos_title": "相片"},
        )
        updated = save_settings_patch(patch)
        self.assertEqual(updated.site.site_title, "新标题")
        self.assertEqual(updated.site.tagline, default_settings().site.tagline)
        self.assertEqual(updated.appearance.accent, "#112233")
        self.assertEqual(updated.copy.photos_title, "相片")
        # Persisted, not just in the returned object.
        reloaded = load_settings()
        self.assertEqual(reloaded.site.site_title, "新标题")
        self.assertEqual(reloaded.appearance.accent, "#112233")

    def test_nested_advanced_patch_merges_within_group(self) -> None:
        patch = SettingsPatch(advanced={"image": {"widths": [800, 1600, 3200]}})
        updated = save_settings_patch(patch)
        self.assertEqual(updated.advanced.image.widths, [800, 1600, 3200])
        # Other image fields keep their defaults.
        self.assertEqual(updated.advanced.image.avif_speed, 6)
        self.assertEqual(updated.advanced.storage.backend, "local")

    def test_invalid_values_are_rejected_before_writing(self) -> None:
        with self.assertRaises(ValidationError):
            SettingsPatch(appearance={"accent": "red"})
        with self.assertRaises(ValidationError):
            SettingsPatch(upload={"max_mb": 0})
        with self.assertRaises(ValidationError):
            SettingsPatch(site={"site_url": "ftp://example.com"})

    def test_public_settings_cache_is_invalidated_on_save(self) -> None:
        load_settings_cached()
        save_settings_patch(SettingsPatch(site={"site_title": "缓存之后"}))
        self.assertEqual(public_settings()["site"]["site_title"], "缓存之后")

    def test_secrets_are_never_stored_in_settings(self) -> None:
        save_settings_patch(
            SettingsPatch(advanced={"storage": {"s3_bucket": "media-bucket"}})
        )
        with closing(connect()) as conn:
            dump = " ".join(
                row["data"] for row in conn.execute("SELECT data FROM settings")
            )
        self.assertIn("media-bucket", dump)
        self.assertNotIn("secret", json.dumps(load_settings().model_dump()))


if __name__ == "__main__":
    unittest.main()

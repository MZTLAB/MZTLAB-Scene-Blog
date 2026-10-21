from __future__ import annotations

import unittest

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


def _settings(**upload_overrides: object) -> Settings:
    settings = Settings()
    for key, value in upload_overrides.items():
        setattr(settings.upload, key, value)
    return settings


class MediaSerializeTests(unittest.TestCase):
    """SQLite stores 0/1; the API must expose a real JSON boolean."""

    def _row(self, auto: int) -> dict:
        return {
            "id": 7,
            "filename": "2026/05/a.jpg",
            "mime": "image/jpeg",
            "size": 1234,
            "width": 800,
            "height": 600,
            "alt": "",
            "exif": "",
            "avif_quality": 33,
            "avif_quality_auto": auto,
            "ready_hash": "",
            "owner_id": 1,
        }

    def test_auto_flag_is_a_boolean(self) -> None:
        auto = _serialize(self._row(1), Settings())
        self.assertIs(auto["avif_quality_auto"], True)
        manual = _serialize(self._row(0), Settings())
        self.assertIs(manual["avif_quality_auto"], False)
        self.assertEqual(manual["avif_quality"], 33)

    def test_owner_comes_from_owner_id_only(self) -> None:
        item = _serialize(self._row(1), Settings())
        self.assertEqual(item["owner"]["id"], 1)
        self.assertEqual(item["owner"]["name"], "未知成员")
        self.assertNotIn("uploaded_by", item)
        self.assertNotIn("effective_owner_id", item)
        self.assertNotIn("ready_hash", item)


class MediaPatchTests(unittest.TestCase):
    """PATCH semantics: omit = keep, explicit null = clear."""

    def _row(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "id": 7,
            "mime": "image/jpeg",
            "alt": "old",
            "avif_quality_auto": 0,
            "avif_quality": 40,
        }
        row.update(overrides)
        return row

    def test_omitted_fields_are_not_written(self) -> None:
        columns = _media_patch_columns(self._row(), MediaAltIn())
        self.assertEqual(columns, {})

    def test_provided_alt_only_changes_alt(self) -> None:
        columns = _media_patch_columns(self._row(), MediaAltIn(alt="new"))
        self.assertEqual(columns, {"alt": "new"})

    def test_null_avif_quality_clears_to_auto_default(self) -> None:
        payload = MediaAltIn.model_validate({"avif_quality": None})
        columns = _media_patch_columns(self._row(), payload)
        self.assertEqual(columns["avif_quality_auto"], 1)
        self.assertEqual(columns["avif_quality"], 55)
        self.assertEqual(columns["ready_hash"], "")

    def test_explicit_manual_quality_is_written(self) -> None:
        payload = MediaAltIn.model_validate({"avif_quality_auto": False, "avif_quality": 60})
        columns = _media_patch_columns(self._row(), payload)
        self.assertEqual(columns["avif_quality_auto"], 0)
        self.assertEqual(columns["avif_quality"], 60)

    def test_audio_rows_ignore_avif_quality(self) -> None:
        payload = MediaAltIn.model_validate({"avif_quality_auto": False, "avif_quality": 60})
        columns = _media_patch_columns(self._row(mime="audio/mpeg"), payload)
        self.assertEqual(columns, {})


class UploadPolicyTests(unittest.TestCase):
    def test_policy_reads_typed_upload_settings(self) -> None:
        max_bytes, images, audio, files = _upload_policy(
            _settings(
                max_mb=5,
                image_formats=["png"],
                audio_formats=["mp3"],
                file_formats=["pdf"],
            )
        )
        self.assertEqual(max_bytes, 5 * 1024 * 1024)
        self.assertEqual(set(images), {"png"})
        self.assertEqual(set(audio), {"mp3"})
        self.assertEqual(set(files), {"pdf"})

    def test_empty_image_or_audio_selection_falls_back_to_the_catalog(self) -> None:
        _, images, audio, files = _upload_policy(
            _settings(image_formats=[], audio_formats=[], file_formats=[])
        )
        self.assertIn("jpg", images)
        self.assertIn("mp3", audio)
        self.assertEqual(files, {})

    def test_max_mb_is_clamped_to_the_technical_ceiling(self) -> None:
        max_bytes, _, _, _ = _upload_policy(_settings(max_mb=10_000))
        self.assertEqual(max_bytes, 200 * 1024 * 1024)


class UploadFormatTests(unittest.TestCase):
    def test_pdf_requires_magic_bytes(self) -> None:
        allowed = {"pdf": FILE_FORMATS["pdf"]}
        self.assertIsNotNone(_file_format(b"%PDF-1.7\n...", "report.pdf", allowed))
        self.assertIsNone(_file_format(b"<html>hi</html>", "report.pdf", allowed))

    def test_ooxml_and_zip_require_zip_container(self) -> None:
        allowed = {
            "docx": FILE_FORMATS["docx"],
            "zip": FILE_FORMATS["zip"],
        }
        self.assertIsNotNone(_file_format(b"PK\x03\x04rest", "notes.docx", allowed))
        self.assertIsNone(_file_format(b"not a zip", "notes.docx", allowed))

    def test_only_enabled_extensions_are_accepted(self) -> None:
        allowed = {"txt": FILE_FORMATS["txt"]}
        self.assertIsNotNone(_file_format(b"hello", "notes.txt", allowed))
        self.assertIsNone(_file_format(b"hello", "notes.md", allowed))

    def test_dangerous_formats_are_not_in_catalog(self) -> None:
        for extension in ("html", "htm", "svg", "js", "mjs", "php", "exe"):
            self.assertNotIn(extension, FILE_FORMATS)

    def test_audio_extension_must_be_enabled(self) -> None:
        allowed = {"mp3": AUDIO_EXTENSIONS["mp3"]}
        mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x00"
        self.assertIsNotNone(_audio_format(mp3, "track.mp3", allowed))
        self.assertIsNone(_audio_format(mp3, "track.wav", allowed))

    def test_admin_any_file_keeps_safe_extension_and_mime(self) -> None:
        extension, mime = _any_file_format("model.glb")
        self.assertEqual(extension, "glb")
        self.assertTrue(mime)
        extension, mime = _any_file_format("notes.weird type")
        self.assertNotIn(" ", extension)
        self.assertNotIn("/", extension)
        self.assertEqual(mime, "application/octet-stream")
        extension, mime = _any_file_format("no-extension")
        self.assertEqual(extension, "bin")
        self.assertEqual(mime, "application/octet-stream")


if __name__ == "__main__":
    unittest.main()

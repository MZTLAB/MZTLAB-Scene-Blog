from __future__ import annotations

import unittest

from app.defaults import default_settings
from app.routes.media import (
    AUDIO_EXTENSIONS,
    FILE_FORMATS,
    _any_file_format,
    _audio_format,
    _file_format,
    _serialize,
)


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
            "uploaded_by": 1,
            "owner_id": 1,
        }

    def test_auto_flag_is_a_boolean(self) -> None:
        auto = _serialize(self._row(1), default_settings())
        self.assertIs(auto["avif_quality_auto"], True)
        manual = _serialize(self._row(0), default_settings())
        self.assertIs(manual["avif_quality_auto"], False)
        self.assertEqual(manual["avif_quality"], 33)


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

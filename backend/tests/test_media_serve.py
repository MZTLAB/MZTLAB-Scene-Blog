"""Download header helpers for original files."""

from __future__ import annotations

import unittest

from app.routes.media_serve import _content_disposition


class ContentDispositionTests(unittest.TestCase):
    def test_keeps_unicode_filename_and_ascii_fallback(self):
        header = _content_disposition("夜色 01.jpg")
        self.assertTrue(header.startswith("attachment;"))
        self.assertIn('filename="', header)
        self.assertIn("filename*=UTF-8''", header)
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)

    def test_strips_header_injection_characters(self):
        header = _content_disposition('evil"\r\nX-Test: 1.jpg')
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        # The ascii fallback must not contain a raw quote.
        fallback = header.split('filename="', 1)[1].split('"', 1)[0]
        self.assertNotIn('"', fallback)

    def test_empty_name_has_a_fallback(self):
        self.assertIn('filename="download"', _content_disposition(""))


if __name__ == "__main__":
    unittest.main()

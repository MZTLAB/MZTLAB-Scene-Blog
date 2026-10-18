from __future__ import annotations

import unittest

from app.content import (
    extract_toc,
    make_excerpt,
    normalize_iso_datetime,
    reading_time,
    render_markdown,
    slugify,
)
from app.security import hash_password, verify_password


class MarkdownTests(unittest.TestCase):
    def test_renders_basic_markdown(self) -> None:
        html = render_markdown("## 标题\n\n**加粗**与[链接](https://example.com)\n\n```js\nconst x = 1;\n```")
        self.assertIn("<h2", html)
        self.assertIn("<strong>加粗</strong>", html)
        self.assertIn('href="https://example.com"', html)
        self.assertIn('class="highlight"', html)

    def test_strips_script_and_event_handlers(self) -> None:
        html = render_markdown(
            '<script>alert(1)</script>\n\n'
            '<img src="x" onerror="alert(1)">\n\n'
            "[bad](javascript:alert(1))"
        )
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("onerror", html.lower())
        self.assertNotIn("javascript:", html.lower())

    def test_allows_html5_audio_embed(self) -> None:
        html = render_markdown(
            '<figure class="audio-embed">'
            '<figcaption>AUDIO · Track</figcaption>'
            '<audio controls preload="metadata">'
            '<source src="https://example.com/track.mp3" type="audio/mpeg">'
            '</audio></figure>'
        )
        self.assertIn("<audio", html)
        self.assertIn("controls", html)
        self.assertIn("<source", html)
        self.assertIn('type="audio/mpeg"', html)

    def test_toc_extraction(self) -> None:
        html = render_markdown("## 第一节\n\n文字\n\n### 小节\n\n## 第二节")
        toc = extract_toc(html)
        self.assertEqual([item["text"] for item in toc], ["第一节", "小节", "第二节"])
        self.assertEqual(toc[1]["level"], 3)

    def test_excerpt_and_reading_time(self) -> None:
        text = "## 标题\n\n" + ("慢下来，看见更多。" * 80)
        excerpt = make_excerpt(text, 60)
        self.assertLessEqual(len(excerpt), 61)
        self.assertGreaterEqual(reading_time(text), 2)

    def test_slugify_supports_cjk(self) -> None:
        self.assertEqual(slugify("你好，世界 Hello World"), "你好-世界-hello-world")
        self.assertEqual(slugify("..."), "post")
        self.assertEqual(slugify("Hello", fallback="page"), "hello")

    def test_datetime_normalization(self) -> None:
        self.assertEqual(normalize_iso_datetime("2026-10-17T12:30"), "2026-10-17T12:30:00Z")
        self.assertEqual(normalize_iso_datetime("2026-10-17T12:30:00+08:00"), "2026-10-17T04:30:00Z")
        self.assertIsNone(normalize_iso_datetime("not-a-date"))


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self) -> None:
        encoded = hash_password("a-good-password")
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertTrue(verify_password("a-good-password", encoded))
        self.assertFalse(verify_password("wrong", encoded))
        self.assertFalse(verify_password("a-good-password", "broken"))


if __name__ == "__main__":
    unittest.main()

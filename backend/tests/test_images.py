"""Image derivative pipeline: settings parsing, URL hashing and encoding."""

from __future__ import annotations

import io
import unittest

from PIL import Image

from app import images
from app.defaults import default_settings


def settings_with(**overrides):
    settings = default_settings()
    settings.update(overrides)
    return settings


class LadderTests(unittest.TestCase):
    def test_parses_and_sorts_the_ladder(self):
        settings = settings_with(image_widths="2560, 720,720, 10, 999999, nope")
        self.assertEqual(images.width_ladder(settings), [720, 2560])

    def test_bad_ladder_falls_back_to_the_default(self):
        self.assertEqual(images.width_ladder(settings_with(image_widths="")), [720, 2560])
        self.assertEqual(images.width_ladder(settings_with(image_widths="10,999999")), [720, 2560])

    def test_scene_widths_follow_the_ladder_and_original(self):
        settings = settings_with(image_widths="720,2560")
        self.assertEqual(images.scene_widths("tile", 4000, settings), [720])
        self.assertEqual(images.scene_widths("card", 4000, settings), [720])
        self.assertEqual(images.scene_widths("hero", 4000, settings), [2560])
        self.assertEqual(images.scene_widths("viewer", 4000, settings), [2560])
        self.assertEqual(images.scene_widths("prose", 4000, settings), [720, 2560])
        self.assertEqual(images.scene_widths("full", 4000, settings), [4000])
        # A smaller original is never upscaled.
        self.assertEqual(images.scene_widths("hero", 1280, settings), [1280])
        self.assertEqual(images.scene_widths("tile", 500, settings), [500])
        self.assertEqual(images.scene_widths("full", 500, settings), [500])

    def test_max_width_caps_the_full_tier_only(self):
        settings = settings_with(image_max_width=3000)
        self.assertEqual(images.scene_widths("full", 6000, settings), [3000])
        self.assertEqual(images.scene_widths("hero", 6000, settings), [2560])

    def test_per_scene_quality_override(self):
        settings = settings_with(image_quality_tile=35, image_quality_hero=62)
        self.assertEqual(images.scene_quality("tile", settings), 35)
        self.assertEqual(images.scene_quality("hero", settings), 62)
        self.assertEqual(images.scene_quality("tile", settings_with(image_quality_tile=500)), 100)

    def test_manual_quality_switch_overrides_scene_quality(self):
        settings = settings_with(image_quality_tile=50, image_webp_quality=77)
        manual = {"avif_quality_auto": 0, "avif_quality": 33}
        auto = {"avif_quality_auto": 1, "avif_quality": 33}
        self.assertEqual(images.quality_for("tile", "avif", settings, manual), 33)
        self.assertEqual(images.quality_for("hero", "avif", settings, manual), 33)
        self.assertEqual(images.quality_for("tile", "avif", settings, auto), 50)
        # WebP/JPEG always use their global quality, whatever the override says.
        self.assertEqual(images.quality_for("tile", "webp", settings, manual), 77)
        self.assertIsNone(images.media_quality_override(auto))
        self.assertEqual(images.media_quality_override(manual), 33)
        # A malformed stored value falls back to the scene setting.
        self.assertIsNone(
            images.media_quality_override({"avif_quality_auto": 0, "avif_quality": 0})
        )


class PayloadTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "id": 42,
            "filename": "2026/05/abc.jpg",
            "mime": "image/jpeg",
            "size": 1_000_000,
            "width": 6000,
            "height": 4000,
            "avif_quality": 55,
            "avif_quality_auto": 1,
            "ready_hash": "",
        }
        row.update(overrides)
        return row

    def test_payload_shape_and_urls(self):
        settings = settings_with(image_widths="720,2560")
        payload = images.image_payload(self._row(), settings)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["width"], 6000)
        self.assertEqual(payload["height"], 4000)
        self.assertEqual(payload["s"], 720)
        self.assertEqual(payload["l"], 2560)
        self.assertEqual(payload["f"], 6000)
        self.assertIn("avif", payload["formats"])
        self.assertTrue(payload["base"].startswith("/media/_v/42/"))
        self.assertIsNone(payload["direct"])
        scene_widths = images.payload_widths("prose", payload)
        self.assertEqual(scene_widths, [720, 2560])

    def test_gif_and_missing_dimensions_have_no_payload(self):
        self.assertIsNone(images.image_payload(self._row(mime="image/gif"), settings_with()))
        self.assertIsNone(images.image_payload(self._row(width=0), settings_with()))
        self.assertIsNone(images.image_payload(self._row(mime="audio/mpeg"), settings_with()))

    def test_hash_changes_when_quality_or_ladder_changes(self):
        row = self._row()
        base = images.variants_hash(row, settings_with())
        self.assertEqual(base, images.variants_hash(row, settings_with()))
        self.assertNotEqual(base, images.variants_hash(row, settings_with(image_quality_full=40)))
        self.assertNotEqual(base, images.variants_hash(row, settings_with(image_widths="640,1920")))
        manual = self._row(avif_quality_auto=0, avif_quality=70)
        self.assertNotEqual(base, images.variants_hash(manual, settings_with()))
        self.assertNotEqual(
            images.variants_hash(manual, settings_with()),
            images.variants_hash(self._row(avif_quality_auto=0, avif_quality=60), settings_with()),
        )

    def test_url_helpers(self):
        settings = settings_with(image_widths="720,2560")
        payload = images.image_payload(self._row(), settings)
        assert payload is not None
        url = images.derivative_url(payload, "tile", 720, "avif")
        self.assertTrue(url.endswith("/tile/720.avif"))
        self.assertEqual(images.url_to_filename("/media/2026/05/abc.jpg"), "2026/05/abc.jpg")
        self.assertIsNone(images.url_to_filename("https://example.com/a.jpg"))


class EncodeTests(unittest.TestCase):
    def _image(self, mode="RGB"):
        image = Image.new(mode, (1600, 1067), (120, 90, 60) if mode == "RGB" else (120, 90, 60, 128))
        return image

    def test_avif_output_has_the_avif_signature(self):
        if not images.AVIF_SUPPORTED:
            self.skipTest("Pillow has no AVIF encoder")
        data, width, height = images._encode(self._image(), 720, "avif", 55, 8)
        self.assertTrue(data[4:12].startswith(b"ftyp"))
        self.assertEqual((width, height), (720, 480))

    def test_webp_and_jpeg_outputs(self):
        webp, _, _ = images._encode(self._image(), 480, "webp", 80, 6)
        self.assertTrue(webp.startswith(b"RIFF"))
        jpeg, _, _ = images._encode(self._image(), 480, "jpeg", 82, 6)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

    def test_never_upscales(self):
        _, width, _ = images._encode(self._image(), 4000, "jpeg", 82, 6)
        self.assertEqual(width, 1600)

    def test_alpha_survives_and_flattens_for_jpeg(self):
        webp, _, _ = images._encode(self._image("RGBA"), 480, "webp", 80, 6)
        self.assertTrue(webp.startswith(b"RIFF"))
        jpeg, _, _ = images._encode(self._image("RGBA"), 480, "jpeg", 82, 6)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

    def test_source_is_rotated_by_exif_orientation(self):
        source = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6  # Orientation: rotate 90°
        self._image().save(source, "JPEG", exif=exif)
        loaded = images._load_source(source.getvalue(), 720)
        try:
            self.assertEqual(loaded.size, (1067, 1600))
        finally:
            loaded.close()


class PictureHtmlTests(unittest.TestCase):
    def test_picture_uses_proxy_handles_for_the_fallback(self):
        settings = settings_with(image_widths="720,2560")
        row = {
            "id": 7, "filename": "2026/05/x.jpg", "mime": "image/jpeg",
            "size": 500, "width": 3000, "height": 2000,
            "avif_quality": 0, "ready_hash": "",
        }
        payload = images.image_payload(row, settings)
        assert payload is not None
        markup = images.picture_html(payload, scene="prose", alt="测试", sizes="820px")
        self.assertIn("<picture>", markup)
        self.assertIn('type="image/avif"', markup)
        self.assertIn('type="image/webp"', markup)
        self.assertIn("/prose/2560.jpg", markup)
        self.assertIn('loading="lazy"', markup)


if __name__ == "__main__":
    unittest.main()

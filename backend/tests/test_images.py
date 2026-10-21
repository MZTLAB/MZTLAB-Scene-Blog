"""Image pipeline: immutable pipeline constants, artifact tokens, read-only payloads."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from PIL import Image, ImageCms

from app import images
from app.settings import Settings


def settings_with(**image_overrides: object) -> Settings:
    """A typed Settings object with selected `advanced.image` fields overridden."""
    settings = Settings()
    for key, value in image_overrides.items():
        setattr(settings.advanced.image, key, value)
    return settings


def row(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": 42,
        "filename": "2026/05/abc.jpg",
        "mime": "image/jpeg",
        "size": 1_000_000,
        "width": 6000,
        "height": 4000,
        "source_sha1": "a" * 40,
        "derivative_set": "",
        "placeholder": "#112233",
    }
    value.update(overrides)
    return value


def ready_derivative_set() -> str:
    media_id = 42
    source = "a" * 40
    artifacts: dict[str, dict[str, dict[str, str]]] = {}
    for scene, width, fmt in (
        ("card", 720, "avif"),
        ("card", 720, "jpeg"),
        ("viewer", 2560, "avif"),
        ("viewer", 2560, "jpeg"),
        ("prose", 720, "avif"),
        ("prose", 2560, "avif"),
        ("prose", 2560, "jpeg"),
    ):
        quality = images.quality_for(scene, fmt)
        token = images.artifact_token(media_id, source, scene, width, fmt, quality)
        artifacts.setdefault(scene, {}).setdefault(str(width), {})[fmt] = token
    return json.dumps(
        {
            "ready": True,
            "pipeline_version": images.PIPELINE_VERSION,
            "s": 720,
            "l": 2560,
            "f": 6000,
            "artifacts": artifacts,
        }
    )


class PipelineDefaultsTests(unittest.TestCase):
    def test_quality_parameters_are_code_constants(self) -> None:
        # ADR-10: quality is not user data; it lives in PIPELINE_DEFAULTS.
        self.assertEqual(images.scene_quality("tile"), 50)
        self.assertEqual(images.scene_quality("full"), 70)
        self.assertEqual(images.quality_for("tile", "avif"), 50)
        self.assertEqual(images.quality_for("tile", "webp"), 80)
        self.assertEqual(images.quality_for("tile", "jpeg"), 82)
        # The settings model no longer exposes encoding knobs.
        self.assertNotIn("avif_speed", Settings().advanced.image.model_fields)
        self.assertNotIn("quality_tile", Settings().advanced.image.model_fields)

    def test_runtime_settings_only_carry_ladder_and_format_switches(self) -> None:
        image = Settings().advanced.image
        self.assertEqual(image.widths, [720, 2560])
        self.assertTrue(image.avif_enabled)
        self.assertTrue(image.webp_enabled)
        self.assertEqual(set(type(image).model_fields), {"widths", "avif_enabled", "webp_enabled"})


class LadderTests(unittest.TestCase):
    def test_parses_and_sorts_the_ladder(self) -> None:
        settings = settings_with(widths=[2560, 720, 720, 10, 999999])
        self.assertEqual(images.width_ladder(settings), [720, 2560])

    def test_bad_ladder_falls_back_to_the_default(self) -> None:
        self.assertEqual(images.width_ladder(settings_with(widths=[])), [720, 2560])
        self.assertEqual(images.width_ladder(settings_with(widths=[10, 999999])), [720, 2560])

    def test_scene_widths_follow_the_ladder_and_original(self) -> None:
        settings = settings_with(widths=[720, 2560])
        self.assertEqual(images.scene_widths("tile", 4000, settings), [720])
        self.assertEqual(images.scene_widths("hero", 4000, settings), [2560])
        self.assertEqual(images.scene_widths("prose", 4000, settings), [720, 2560])
        self.assertEqual(images.scene_widths("full", 4000, settings), [4000])
        # A smaller original is never upscaled.
        self.assertEqual(images.scene_widths("hero", 1280, settings), [1280])
        self.assertEqual(images.scene_widths("tile", 500, settings), [500])

    def test_full_tier_cap_is_a_pipeline_constant(self) -> None:
        settings = settings_with()
        with patch.dict(images.PIPELINE_DEFAULTS, {"max_width": 3000}):
            self.assertEqual(images.scene_widths("full", 6000, settings), [3000])
            self.assertEqual(images.full_width(6000), 3000)
            self.assertEqual(images.scene_widths("hero", 6000, settings), [2560])
        self.assertEqual(images.full_width(6000), 6000)

    def test_generation_formats_follow_the_typed_switches(self) -> None:
        both = images.generation_formats(settings_with())
        self.assertIn("jpeg", both)
        self.assertIn("avif", both)
        self.assertIn("webp", both)
        no_avif = settings_with(avif_enabled=False)
        self.assertNotIn("avif", images.generation_formats(no_avif))
        self.assertNotIn("avif", images.source_formats(no_avif))


class ArtifactTokenTests(unittest.TestCase):
    def test_token_is_stable_and_covers_every_input(self) -> None:
        base = images.artifact_token(42, "a" * 40, "card", 720, "avif", 55)
        self.assertEqual(base, images.artifact_token(42, "a" * 40, "card", 720, "avif", 55))
        self.assertEqual(len(base), 10)
        self.assertNotEqual(base, images.artifact_token(42, "b" * 40, "card", 720, "avif", 55))
        self.assertNotEqual(base, images.artifact_token(42, "a" * 40, "card", 800, "avif", 55))
        self.assertNotEqual(base, images.artifact_token(42, "a" * 40, "card", 720, "webp", 80))
        self.assertNotEqual(base, images.artifact_token(42, "a" * 40, "card", 720, "avif", 60))
        with patch.object(images, "PIPELINE_VERSION", images.PIPELINE_VERSION + 1):
            self.assertNotEqual(
                base, images.artifact_token(42, "a" * 40, "card", 720, "avif", 55)
            )


class PayloadTests(unittest.TestCase):
    def test_not_ready_payload_advertises_no_derivatives(self) -> None:
        payload = images.image_payload(row(), settings_with(widths=[720, 2560]))
        assert payload is not None
        self.assertEqual(payload["id"], 42)
        self.assertEqual((payload["width"], payload["height"]), (6000, 4000))
        self.assertEqual((payload["s"], payload["l"], payload["f"]), (720, 2560, 6000))
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["formats"], [])
        self.assertEqual(payload["artifacts"], [])
        self.assertEqual(payload["base"], "/media/_v/42")
        self.assertIsNone(payload["direct_base"])
        self.assertEqual(payload["placeholder"], "#112233")

    def test_ready_payload_exposes_tokens_and_urls(self) -> None:
        payload = images.image_payload(
            row(derivative_set=ready_derivative_set()), settings_with(widths=[720, 2560])
        )
        assert payload is not None
        self.assertTrue(payload["ready"])
        self.assertIn("avif", payload["formats"])
        self.assertTrue(payload["artifacts"])
        token = next(
            artifact["token"]
            for artifact in payload["artifacts"]
            if artifact["scene"] == "prose"
            and artifact["width"] == 2560
            and artifact["format"] == "avif"
        )
        self.assertEqual(
            images.artifact_url(payload, "prose", 2560, "avif"),
            f"/media/_v/42/{token}/prose/2560.avif",
        )
        self.assertEqual(
            images.artifact_url(payload, "prose", 720, "webp"),
            "",
            "a missing artifact must not fabricate a URL",
        )
        self.assertEqual(images.payload_widths("prose", payload), [720, 2560])

    def test_gif_and_missing_dimensions_have_no_payload(self) -> None:
        self.assertIsNone(images.image_payload(row(mime="image/gif"), settings_with()))
        self.assertIsNone(images.image_payload(row(width=0), settings_with()))
        self.assertIsNone(images.image_payload(row(mime="audio/mpeg"), settings_with()))

    def test_url_to_filename(self) -> None:
        self.assertEqual(images.url_to_filename("/media/2026/05/abc.jpg"), "2026/05/abc.jpg")
        self.assertIsNone(images.url_to_filename("https://example.com/a.jpg"))


class EncodeTests(unittest.TestCase):
    def _image(self, mode: str = "RGB") -> Image.Image:
        color = (120, 90, 60) if mode == "RGB" else (120, 90, 60, 128)
        return Image.new(mode, (1600, 1067), color)

    def test_avif_output_has_the_avif_signature(self) -> None:
        if not images.AVIF_SUPPORTED:
            self.skipTest("Pillow has no AVIF encoder")
        data, width, height = images._encode(self._image(), 720, "avif", 55, 8)
        self.assertTrue(data[4:12].startswith(b"ftyp"))
        self.assertEqual((width, height), (720, 480))

    def test_avif_keeps_the_icc_profile(self) -> None:
        if not images.AVIF_SUPPORTED:
            self.skipTest("Pillow has no AVIF encoder")
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        image = self._image()
        image.info["icc_profile"] = profile
        try:
            data, _, _ = images._encode(image, 720, "avif", 55, 8)
        finally:
            image.close()
        embedded = Image.open(io.BytesIO(data)).info.get("icc_profile")
        self.assertEqual(embedded, profile)

    def test_webp_and_jpeg_outputs(self) -> None:
        webp, _, _ = images._encode(self._image(), 480, "webp", 80, 6)
        self.assertTrue(webp.startswith(b"RIFF"))
        jpeg, _, _ = images._encode(self._image(), 480, "jpeg", 82, 6)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

    def test_never_upscales(self) -> None:
        _, width, _ = images._encode(self._image(), 4000, "jpeg", 82, 6)
        self.assertEqual(width, 1600)

    def test_alpha_survives_and_flattens_for_jpeg(self) -> None:
        webp, _, _ = images._encode(self._image("RGBA"), 480, "webp", 80, 6)
        self.assertTrue(webp.startswith(b"RIFF"))
        jpeg, _, _ = images._encode(self._image("RGBA"), 480, "jpeg", 82, 6)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

    def test_source_is_rotated_by_exif_orientation(self) -> None:
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
    def test_picture_uses_ready_artifacts_and_a_proxy_fallback(self) -> None:
        payload = images.image_payload(
            row(derivative_set=ready_derivative_set()), settings_with(widths=[720, 2560])
        )
        assert payload is not None
        markup = images.picture_html(payload, scene="prose", alt="测试", sizes="820px")
        self.assertIn("<picture>", markup)
        self.assertIn('type="image/avif"', markup)
        self.assertIn("/prose/2560.avif", markup)
        self.assertIn("/prose/2560.jpg", markup)
        self.assertIn('loading="lazy"', markup)

    def test_not_ready_payload_renders_no_picture(self) -> None:
        payload = images.image_payload(row(), settings_with())
        assert payload is not None
        self.assertEqual(
            images.picture_html(payload, scene="prose", alt="x", sizes="820px"), ""
        )


if __name__ == "__main__":
    unittest.main()

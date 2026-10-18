from __future__ import annotations

import json
import unittest
from io import BytesIO

from PIL import Image

from app.exif import dump_exif, parse_stored, photo_defaults, read_exif_bytes


def _jpeg_with_exif() -> bytes:
    image = Image.new("RGB", (24, 16), (18, 26, 34))
    exif = Image.Exif()
    exif[0x010F] = "MZTLAB"
    exif[0x0110] = "Scene One"
    exif[0x0131] = "Scene test"
    exif[0x0132] = "2024:05:01 12:34:56"
    exif[0x8769] = {
        0x9003: "2024:05:01 12:34:56",
        0xA434: "35mm Prime",
        0x829D: 2.8,
        0x829A: (1, 250),
        0x8827: 400,
        0x920A: 35.0,
    }
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


class ExifTests(unittest.TestCase):
    def test_reads_camera_lens_and_exposure(self) -> None:
        info = read_exif_bytes(_jpeg_with_exif())
        self.assertIsNotNone(info)
        assert info is not None
        self.assertTrue(info["found"])
        self.assertIn("Scene One", info["camera"])
        self.assertEqual(info["lens"], "35mm Prime")
        self.assertEqual(info["taken_at"], "2024-05-01")
        self.assertEqual(info["aperture"], "f/2.8")
        self.assertEqual(info["exposure"], "1/250s")
        self.assertEqual(info["iso"], 400)
        self.assertEqual(info["focal_length"], "35mm")

    def test_photo_defaults_fit_the_schema(self) -> None:
        defaults = photo_defaults(read_exif_bytes(_jpeg_with_exif()))
        self.assertIn("Scene One", defaults["camera"])
        self.assertEqual(defaults["lens"], "35mm Prime")
        self.assertEqual(defaults["taken_at"], "2024-05-01")
        self.assertLessEqual(len(defaults["camera"]), 120)
        self.assertLessEqual(len(defaults["lens"]), 120)
        self.assertLessEqual(len(defaults["taken_at"]), 10)

    def test_stored_round_trip_is_json_safe(self) -> None:
        info = read_exif_bytes(_jpeg_with_exif())
        dumped = dump_exif(info)
        self.assertIsInstance(dumped, str)
        json.loads(dumped)  # must not raise
        self.assertEqual(parse_stored(dumped), info)
        self.assertIsNone(parse_stored(""))
        self.assertIsNone(parse_stored("not json"))

    def test_plain_image_has_no_exif(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (8, 8), (0, 0, 0)).save(buffer, format="PNG")
        self.assertIsNone(read_exif_bytes(buffer.getvalue()))

    def test_gps_is_converted_to_decimal_degrees(self) -> None:
        image = Image.new("RGB", (12, 12), (1, 2, 3))
        exif = Image.Exif()
        exif[0x010F] = "Make"
        exif[0x0110] = "Model"
        exif[0x0132] = "2024:05:01 12:00:00"
        exif[0x8825] = {
            1: "N",
            2: (31.0, 14.0, 30.0),
            3: "E",
            4: (121.0, 28.0, 12.0),
            5: 0,
            6: (12.5,),
        }
        buffer = BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        info = read_exif_bytes(buffer.getvalue())
        assert info is not None
        self.assertIsNotNone(info["gps"])
        assert info["gps"] is not None
        self.assertAlmostEqual(info["gps"]["latitude"], 31.241667, places=5)
        self.assertAlmostEqual(info["gps"]["longitude"], 121.47, places=3)
        self.assertEqual(info["gps"]["altitude"], 12.5)

    def test_broken_file_is_not_an_exception(self) -> None:
        self.assertIsNone(read_exif_bytes(b"definitely not an image"))


if __name__ == "__main__":
    unittest.main()

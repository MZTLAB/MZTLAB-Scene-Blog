"""Read camera metadata (EXIF) from uploaded photographs.

The media library validates uploads with Pillow already, so reading EXIF needs
no extra dependency. We normalise the handful of fields the admin UI cares
about (camera, lens, capture date, exposure, GPS) and keep a small JSON-safe
snapshot of the raw tags for the detail dialog.

Nothing here ever writes to the original file. The parsed dict is stored as
JSON in `media.exif` and re-read from disk by `/api/admin/media/{id}/exif` when
an older upload has no cached copy.
"""

from __future__ import annotations

import json
import math
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, UnidentifiedImageError
from PIL.ExifTags import IFD

_MAX_RAW_KEYS = 80
_MAX_TEXT = 240

# Tags whose values are offsets/blob payloads rather than useful metadata.
_SKIP_TAGS = {0x8769, 0x8825, 0x927C, 0xA005}  # ExifOffset, GPSInfo, MakerNote, Interop


def _tag_name(tag: int, *, gps: bool = False) -> str:
    if gps:
        return ExifTags.GPSTAGS.get(tag, f"GPS:{tag:#06x}")
    return ExifTags.TAGS.get(tag, f"Tag:{tag:#06x}")


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Convert Pillow EXIF values (rationals, tuples, bytes) to JSON values."""
    if depth > 3:
        return _text(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value if not isinstance(value, str) else value[:_MAX_TEXT]
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else None
    if isinstance(value, bytes):
        # Maker notes / thumbnails are binary noise in a JSON export.
        return None
    if isinstance(value, dict):
        return {
            _tag_name(int(key)) if isinstance(key, int) else str(key): _json_safe(item, depth + 1)
            for key, item in list(value.items())[:_MAX_RAW_KEYS]
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth + 1) for item in list(value)[:24]]
    try:
        number = float(value)
        return round(number, 6) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return _text(value)


def _text(value: Any) -> str:
    if value is None or isinstance(value, bytes):
        return ""
    return str(value).replace("\x00", "").strip()[:_MAX_TEXT]


def _rational(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        try:
            numerator, denominator = value  # type: ignore[misc]
            return float(numerator) / float(denominator) if denominator else None
        except (TypeError, ValueError, ZeroDivisionError):
            return None


def _exposure(value: Any) -> str:
    seconds = _rational(value)
    if seconds is None or seconds <= 0:
        return ""
    if seconds < 1:
        return f"1/{max(1, round(1 / seconds))}s"
    if seconds >= 60:
        return f"{seconds / 60:g}min"
    return f"{seconds:g}s"


def _aperture(value: Any) -> str:
    number = _rational(value)
    return f"f/{number:g}" if number else ""


def _focal_length(value: Any) -> str:
    number = _rational(value)
    return f"{number:g}mm" if number else ""


def _iso(value: Any) -> int | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 409_600 else None


def _gps_degrees(value: Any) -> float | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    parts = [_rational(part) for part in list(value)[:3]]
    if not parts or parts[0] is None:
        return None
    degrees = parts[0]
    if len(parts) > 1 and parts[1] is not None:
        degrees += parts[1] / 60
    if len(parts) > 2 and parts[2] is not None:
        degrees += parts[2] / 3600
    return round(degrees, 6)


def _gps(gps_ifd: dict[int, Any]) -> dict[str, Any] | None:
    if not gps_ifd:
        return None
    latitude = _gps_degrees(gps_ifd.get(2))
    longitude = _gps_degrees(gps_ifd.get(4))
    if latitude is None or longitude is None:
        return None
    if str(gps_ifd.get(1, "")).upper() in {"S", "SOUTH"}:
        latitude = -latitude
    if str(gps_ifd.get(3, "")).upper() in {"W", "WEST"}:
        longitude = -longitude
    altitude = _rational(gps_ifd.get(6))
    if (
        altitude is not None
        and str(gps_ifd.get(5, "")).lstrip("\x00").isdigit()
        and int(gps_ifd.get(5, 0)) == 1
    ):
        altitude = -altitude
    result: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
    }
    if altitude is not None:
        result["altitude"] = round(altitude, 2)
    return result


def _taken_at(*values: Any) -> tuple[str, str]:
    """Return (YYYY-MM-DD, raw) from an EXIF datetime string."""
    for value in values:
        raw = _text(value)
        if not raw:
            continue
        # EXIF uses "YYYY:MM:DD HH:MM:SS"; some cameras only write the date.
        normalized = raw.replace("\x00", "").strip()
        parts = normalized.replace(":", "-", 2).split(" ")
        date = parts[0].strip()
        if len(date) >= 10 and date[4] == "-" and date[7] == "-":
            return date[:10], normalized
    return "", ""


def read_exif_bytes(data: bytes) -> dict[str, Any] | None:
    """Parse EXIF from image bytes. Returns None when the file has no EXIF."""
    try:
        with Image.open(BytesIO(data)) as image:
            return _read(image)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return None


def read_exif_file(path: str | Path) -> dict[str, Any] | None:
    """Parse EXIF from a file on disk."""
    try:
        with Image.open(path) as image:
            return _read(image)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return None


def _read(image: Image.Image) -> dict[str, Any] | None:
    try:
        exif = image.getexif()
    except (AttributeError, OSError, ValueError, SyntaxError, KeyError, TypeError):
        return None
    if not exif:
        return None

    try:
        exif_ifd = dict(exif.get_ifd(IFD.Exif))
    except (KeyError, TypeError, ValueError):
        exif_ifd = {}
    try:
        gps_ifd = dict(exif.get_ifd(IFD.GPSInfo))
    except (KeyError, TypeError, ValueError):
        gps_ifd = {}

    make = _text(exif.get(0x010F))
    model = _text(exif.get(0x0110))
    camera = " ".join(part for part in (make, model) if part)
    if make and model.lower().startswith(make.lower()):
        camera = model

    lens = _text(exif_ifd.get(0xA434) or exif_ifd.get(0xA433) or exif.get(0xA434))
    taken_at, taken_raw = _taken_at(
        exif_ifd.get(0x9003),  # DateTimeOriginal
        exif_ifd.get(0x9004),  # DateTimeDigitized
        exif.get(0x0132),      # DateTime
    )

    raw: dict[str, Any] = {}
    for tag, value in list(exif.items()):
        if int(tag) in _SKIP_TAGS:
            continue
        raw[_tag_name(int(tag))] = _json_safe(value)
    for tag, value in list(exif_ifd.items()):
        if int(tag) in _SKIP_TAGS:
            continue
        raw[_tag_name(int(tag))] = _json_safe(value)
    for tag, value in list(gps_ifd.items()):
        raw[_tag_name(int(tag), gps=True)] = _json_safe(value)

    result: dict[str, Any] = {
        "found": True,
        "camera": camera[:120],
        "make": make[:80],
        "model": model[:80],
        "lens": lens[:120],
        "taken_at": taken_at,
        "taken_at_raw": taken_raw,
        "exposure": _exposure(exif_ifd.get(0x829A)),
        "aperture": _aperture(exif_ifd.get(0x829D)),
        "iso": _iso(exif_ifd.get(0x8827) or exif.get(0x8827)),
        "focal_length": _focal_length(exif_ifd.get(0x920A)),
        "focal_length_35mm": _iso(exif_ifd.get(0xA405)),
        "orientation": _json_safe(exif.get(0x0112)),
        "software": _text(exif.get(0x0131)),
        "artist": _text(exif.get(0x013B)),
        "copyright": _text(exif.get(0x8298)),
        "gps": _gps(gps_ifd),
        "raw": raw,
    }
    # A file can carry an almost-empty EXIF block; treat that as no metadata.
    if not (camera or lens or taken_at or result["exposure"] or result["gps"]):
        return None
    return result


def parse_stored(value: Any) -> dict[str, Any] | None:
    """Read the JSON blob stored on a media row."""
    if not value:
        return None
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def dump_exif(exif: dict[str, Any] | None) -> str:
    if not exif:
        return ""
    return json.dumps(exif, ensure_ascii=False, separators=(",", ":"))


def photo_defaults(exif: dict[str, Any] | None) -> dict[str, str]:
    """Fields a new gallery photo can inherit from the media EXIF block."""
    if not exif:
        return {"camera": "", "lens": "", "taken_at": ""}
    taken = str(exif.get("taken_at") or "")[:10]
    if len(taken) != 10 or taken[4] != "-" or taken[7] != "-":
        taken = ""
    return {
        "camera": str(exif.get("camera") or "")[:120],
        "lens": str(exif.get("lens") or "")[:120],
        "taken_at": taken,
    }


def summary(exif: dict[str, Any] | None) -> str:
    """One-line human summary used in toasts/tests."""
    if not exif:
        return "这张图片没有可读取的 EXIF 信息"
    parts = [
        str(exif.get("camera") or ""),
        str(exif.get("lens") or ""),
        str(exif.get("taken_at") or ""),
        str(exif.get("aperture") or ""),
        str(exif.get("exposure") or ""),
        f"ISO {exif['iso']}" if exif.get("iso") else "",
    ]
    return " · ".join(part for part in parts if part) or "已读取 EXIF"

"""Per-photo EXIF visibility.

Public pages should be able to show a subset of a photo's technical metadata.
The stored value is a comma-separated allow-list; an empty string means the
photographer chose to hide every EXIF field.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

EXIF_FIELDS: tuple[str, ...] = (
    "camera",
    "lens",
    "focal_length",
    "aperture",
    "exposure",
    "iso",
    "taken_at",
    "dimensions",
)

DEFAULT_EXIF_FIELDS: tuple[str, ...] = EXIF_FIELDS


def parse_stored_exif_fields(value: Any) -> list[str]:
    """Read a stored allow-list. NULL means all fields (legacy rows)."""
    if value is None:
        return list(DEFAULT_EXIF_FIELDS)
    if isinstance(value, (list, tuple, set)):
        wanted = {str(item) for item in value}
    else:
        wanted = {part.strip() for part in str(value).split(",") if part.strip()}
    return [field for field in EXIF_FIELDS if field in wanted]


def normalize_exif_fields(value: Iterable[str] | str | None) -> list[str] | None:
    """Validate an API value while preserving None for partial updates."""
    if value is None:
        return None
    if isinstance(value, str):
        parts: Iterable[str] = value.split(",")
    else:
        parts = value
    wanted = {str(part).strip() for part in parts if str(part).strip()}
    return [field for field in EXIF_FIELDS if field in wanted]


def dump_exif_fields(fields: Iterable[str] | None) -> str:
    return ",".join(normalize_exif_fields(fields) or [])

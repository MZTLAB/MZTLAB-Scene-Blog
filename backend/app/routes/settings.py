"""Admin settings API for the grouped settings documents.

Settings are five validated JSON documents (`site`, `appearance`, `copy`,
`upload`, `advanced`). This router only exposes the typed document plus display
metadata; S3 credentials are environment-only and surface as `*_configured`
booleans, never as values.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..api.models import AdminSettingsResponse, AdminSettingsUpdateResponse
from ..config import VERSION
from ..deps import require_permission, require_staff
from ..images import AVIF_SUPPORTED, WEBP_SUPPORTED
from ..settings import SettingsPatch, load_settings, save_settings_patch
from ..settings.models import (
    COLOR_MODES,
    FONT_PAIRS,
    HERO_STYLES,
    IMAGE_SCENES,
    POST_LAYOUTS,
    STORAGE_BACKENDS,
    STORAGE_SERVE_MODES,
    THEMES,
)
from ..storage import reset_storage, storage_config

router = APIRouter(
    prefix="/admin",
    tags=["settings"],
    dependencies=[Depends(require_staff)],
)


def _storage_secrets() -> dict[str, bool]:
    config = storage_config()
    return {
        "access_key_configured": bool(config.access_key),
        "secret_key_configured": bool(config.secret_key),
    }


def _meta() -> dict[str, Any]:
    secrets = _storage_secrets()
    return {
        "version": VERSION,
        "themes": sorted(THEMES),
        "color_modes": sorted(COLOR_MODES),
        "font_pairs": sorted(FONT_PAIRS),
        "post_layouts": sorted(POST_LAYOUTS),
        "hero_styles": sorted(HERO_STYLES),
        "image": {
            "avif": AVIF_SUPPORTED,
            "webp": WEBP_SUPPORTED,
            "scenes": list(IMAGE_SCENES),
        },
        "storage": {
            "backends": sorted(STORAGE_BACKENDS),
            "serve_modes": sorted(STORAGE_SERVE_MODES),
            **secrets,
        },
    }


def _document() -> dict[str, Any]:
    return load_settings().model_dump()


def _updated_paths(provided: dict[str, dict[str, object]]) -> list[str]:
    paths: list[str] = []
    for group, fields in provided.items():
        for field, value in fields.items():
            if isinstance(value, dict):
                paths.extend(
                    f"{group}.{field}.{sub_field}" for sub_field in value
                )
            else:
                paths.append(f"{group}.{field}")
    return sorted(paths)


@router.get("/settings", response_model=AdminSettingsResponse)
def get_settings(
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    return {
        "settings": _document(),
        "meta": _meta(),
        "storage_secrets": _storage_secrets(),
    }


@router.patch("/settings", response_model=AdminSettingsUpdateResponse)
def update_settings(
    payload: SettingsPatch,
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    provided = payload.provided()
    if provided:
        save_settings_patch(payload)
        # A storage / image change invalidates the cached backend and the
        # derivative-addressing configuration, so rebuild it together.
        reset_storage()
    return {
        "ok": True,
        "settings": _document(),
        "updated": _updated_paths(provided),
        "meta": _meta(),
        "storage_secrets": _storage_secrets(),
    }

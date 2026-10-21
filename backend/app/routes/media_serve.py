"""Serve uploaded originals and generated image derivatives.

Originals are addressed as `/media/{path}`; derivatives as
`/media/_v/{media_id}/{token}/{scene}/{width}.{ext}`. A derivative is only
served when a `media_derivatives` row with exactly those coordinates exists —
the read path never encodes (R4 / decision D5); a missing artifact row is a 404
and the frontend falls back to the original.

Both routes go through `Storage.size()` + `Storage.stream()` only (no
`local_path`, no backend branch): local disk, S3 and the mirror wrapper are
served by the same code. Immutable derivative URLs get a one-year cache header;
originals keep the existing Content-Disposition / sandbox-CSP rules.

Known Phase 4 gap (BC-21): executable/active media is still detected from the
extension because there is no `media.force_download` column yet. When that
column lands, replace `ACTIVE_MEDIA_EXTENSIONS` with the stored flag.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from ..db import db
from ..images import EXT_FORMAT, SCENES
from ..storage import (
    StorageError,
    StorageMissing,
    content_type_for,
    get_storage,
)

logger = logging.getLogger("mztlab.media")

router = APIRouter(tags=["media"])

# Administrators may upload any file type. Anything a browser could execute on
# the site's origin is served as a download with a locked-down CSP instead of
# being rendered inline. Phase 4 will read this from `media.force_download`.
ACTIVE_MEDIA_EXTENSIONS = {
    "html",
    "htm",
    "xhtml",
    "shtml",
    "svg",
    "xml",
    "xsl",
    "js",
    "mjs",
    "cjs",
    "css",
    "php",
    "phtml",
    "asp",
    "aspx",
    "jsp",
    "exe",
    "dll",
    "com",
    "bat",
    "cmd",
    "ps1",
    "sh",
    "wasm",
    "swf",
}

_SAFE_KEY = re.compile(r"^[A-Za-z0-9_\-./]+$")
_DERIVATIVE_NAME = re.compile(r"^(\d{1,5})\.(avif|webp|jpg)$")


def _content_disposition(filename: str) -> str:
    """Build a safe attachment header that keeps the original (Unicode) name."""
    cleaned = re.sub(r"[\r\n\"\\/]", "_", filename).strip() or "download"
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned).strip("._") or "download"
    if "." not in ascii_name:
        suffix = Path(cleaned).suffix
        if suffix:
            ascii_name += suffix
    return (
        f"attachment; filename=\"{ascii_name[:150]}\"; filename*=UTF-8''{quote(cleaned, safe='')}"
    )


def _send(
    key: str,
    *,
    cache_seconds: int,
    attachment: bool = False,
    download_name: str | None = None,
) -> Response:
    """Stream one storage object; no filesystem access and no backend branches."""
    storage = get_storage()
    headers = {"Cache-Control": f"public, max-age={cache_seconds}"}
    if download_name:
        headers["Content-Disposition"] = _content_disposition(download_name)
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    elif attachment:
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    media_type = content_type_for(key)

    try:
        size = storage.size(key)
    except StorageMissing as error:
        raise HTTPException(status_code=404, detail="文件不存在") from error
    except StorageError as error:
        logger.error("storage size failed for %s: %s", key, error)
        raise HTTPException(status_code=502, detail="对象存储暂时不可用") from error
    headers["Content-Length"] = str(max(0, size))

    try:
        chunks = storage.stream(key)
    except StorageMissing as error:
        raise HTTPException(status_code=404, detail="文件不存在") from error
    except StorageError as error:
        logger.error("storage stream failed for %s: %s", key, error)
        raise HTTPException(status_code=502, detail="对象存储暂时不可用") from error
    return StreamingResponse(chunks, media_type=media_type, headers=headers)


@router.get("/media/_v/{media_id}/{token}/{scene}/{name}")
def image_derivative(
    media_id: int, token: str, scene: str, name: str
) -> Response:
    """Serve an existing derivative row; never generate one on request."""
    if scene not in SCENES:
        raise HTTPException(status_code=404, detail="未知的图片场景")
    matched = _DERIVATIVE_NAME.match(name)
    if not matched:
        raise HTTPException(status_code=404, detail="未知的图片尺寸")
    width = int(matched.group(1))
    fmt = EXT_FORMAT[matched.group(2)]

    with db() as conn:
        row = conn.execute(
            """SELECT key FROM media_derivatives
               WHERE media_id = ? AND token = ? AND scene = ?
                 AND width = ? AND format = ?""",
            (media_id, token, scene, width, fmt),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="图片派生资源不存在")
    return _send(str(row["key"]), cache_seconds=31536000)


@router.get("/media/{path:path}")
def media_file(path: str, download: bool = False) -> Response:
    key = (path or "").strip()
    if not key or key.startswith("/") or ".." in key or "\\" in key or not _SAFE_KEY.match(key):
        raise HTTPException(status_code=400, detail="非法路径")
    extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    attachment = extension in ACTIVE_MEDIA_EXTENSIONS
    download_name: str | None = None
    if download:
        # Prefer the original filename for the browser's "save as" dialog.
        with db() as conn:
            row = conn.execute(
                "SELECT original_name FROM media WHERE filename = ?", (key,)
            ).fetchone()
        download_name = (
            str(row["original_name"]).strip()
            if row and str(row["original_name"]).strip()
            else key.rsplit("/", 1)[-1]
        )
    return _send(
        key,
        cache_seconds=86400 if download else 604800,
        attachment=attachment,
        download_name=download_name,
    )


__all__ = ["router", "ACTIVE_MEDIA_EXTENSIONS"]

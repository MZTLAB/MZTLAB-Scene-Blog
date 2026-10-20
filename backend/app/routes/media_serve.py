"""Serve uploaded originals and generated image derivatives.

Derivatives are generated on first request (and pre-warmed after upload) under
`/media/_v/{media_id}/{token}/{scene}/{width}.{ext}`. When object storage is
configured with a public base URL the backend redirects to it; otherwise the
file is streamed from the bucket or local disk. URLs are immutable, so they can
be cached for a year.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from ..db import db, load_settings_cached
from ..images import (
    EXT_FORMAT,
    SCENES,
    SkipDerivative,
    ensure_derivative,
    generation_formats,
    is_image_row,
    scene_widths,
)
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
# being rendered inline.
ACTIVE_MEDIA_EXTENSIONS = {
    "html", "htm", "xhtml", "shtml", "svg", "xml", "xsl", "js", "mjs",
    "cjs", "css", "php", "phtml", "asp", "aspx", "jsp", "exe", "dll",
    "com", "bat", "cmd", "ps1", "sh", "wasm", "swf",
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
        f"attachment; filename=\"{ascii_name[:150]}\"; "
        f"filename*=UTF-8''{quote(cleaned, safe='')}"
    )


def _send(
    key: str,
    *,
    cache_seconds: int,
    attachment: bool = False,
    allow_redirect: bool = True,
    download_name: str | None = None,
) -> Response:
    storage = get_storage()
    headers = {"Cache-Control": f"public, max-age={cache_seconds}"}
    if download_name:
        headers["Content-Disposition"] = _content_disposition(download_name)
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        # The attachment header must survive, so never hand the request over
        # to a storage redirect for downloads.
        allow_redirect = False
    elif attachment:
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        allow_redirect = False
    media_type = content_type_for(key)

    try:
        local = storage.local_path(key)
    except StorageError as error:
        raise HTTPException(status_code=400, detail="非法路径") from error

    if local is not None:
        if not local.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(local, media_type=media_type, headers=headers)

    if allow_redirect:
        public = storage.public_url(key)
        if not public:
            presigned = getattr(storage, "presigned_url", None)
            public = presigned(key) if presigned else None
        if public:
            return RedirectResponse(public, status_code=302, headers=headers)

    try:
        chunks = storage.stream(key)
    except StorageMissing as error:
        raise HTTPException(status_code=404, detail="文件不存在") from error
    except StorageError as error:
        logger.error("storage stream failed for %s: %s", key, error)
        raise HTTPException(status_code=502, detail="对象存储暂时不可用") from error
    return StreamingResponse(chunks, media_type=media_type, headers=headers)


@router.get("/media/_v/{media_id}/{token}/{scene}/{name}")
def image_derivative(media_id: int, token: str, scene: str, name: str) -> Response:
    if scene not in SCENES:
        raise HTTPException(status_code=404, detail="未知的图片场景")
    matched = _DERIVATIVE_NAME.match(name)
    if not matched:
        raise HTTPException(status_code=404, detail="未知的图片尺寸")
    width = int(matched.group(1))
    fmt = EXT_FORMAT[matched.group(2)]

    settings = load_settings_cached()
    if fmt not in generation_formats(settings):
        raise HTTPException(status_code=404, detail="该图片格式未启用")
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if not is_image_row(row):
        raise HTTPException(status_code=404, detail="图片不存在")
    allowed = scene_widths(scene, int(row["width"] or 0), settings)
    if width not in allowed:
        raise HTTPException(status_code=404, detail="未知的图片尺寸")
    try:
        key = ensure_derivative(row, settings, scene, width, fmt)
    except SkipDerivative as error:
        raise HTTPException(status_code=404, detail="该图片不支持派生格式") from error
    except StorageError as error:
        logger.error("derivative generation failed for media %s: %s", media_id, error)
        raise HTTPException(status_code=502, detail="图片生成暂时不可用") from error
    return _send(key, cache_seconds=31536000)


@router.get("/media/{path:path}")
def media_file(path: str, download: bool = False) -> Response:
    key = (path or "").strip()
    if (
        not key
        or key.startswith("/")
        or ".." in key
        or "\\" in key
        or not _SAFE_KEY.match(key)
    ):
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
        allow_redirect=not attachment,
        download_name=download_name,
    )


__all__ = ["router", "ACTIVE_MEDIA_EXTENSIONS"]

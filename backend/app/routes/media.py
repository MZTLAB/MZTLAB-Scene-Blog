"""Media library: streamed uploads, ownership, EXIF, listing, deletion.

3.0.0 changes (P-H1/P-H2, BC-16):

* `upload_media` is a **synchronous** route (thread pool, never the event loop).
  It streams the `UploadFile` into a temporary file in 1 MB chunks, hashing
  SHA-1 as it goes, aborts with 413 as soon as the limit is crossed, validates
  the temp file with Pillow, then atomically moves it to
  `uploads/YYYY/MM/{uuid}.{ext}`. The file is never read into memory.
* Uploading an image enqueues one `prewarm` job (jobs table); audio/files don't.
* Per-image AVIF quality is gone (BC-34): the image pipeline publishes through
  `media.derivative_set` and the API exposes `images.image_payload`.

Every file has an owner (`media.owner_id`). Ownership checks go through
`app.services.authz.authorize`.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import mimetypes
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from ..api.models import (
    ExifPayload,
    ImagePayload,
    MediaDeleteResponse,
    MediaExifResponse,
    Pagination,
    StorageStatusResponse,
    StorageTestResponse,
)
from ..config import ADMIN_MAX_UPLOAD_BYTES, UPLOAD_DIR
from ..db import db, now_iso
from ..deps import require_permission, require_staff
from ..exif import dump_exif, parse_stored, read_exif_file, summary
from ..images import (
    AVIF_SUPPORTED,
    WEBP_SUPPORTED,
    delete_derivatives,
    derivative_stats,
    image_payload,
    is_image_row,
)
from ..jobs import enqueue_job
from ..permissions import can
from ..posts import pagination
from ..schemas import MediaAltIn, MediaExifIn, StorageSyncIn
from ..services.authz import authorize
from ..settings import Settings, load_settings, load_settings_cached
from ..storage import (
    StorageError,
    get_remote_storage,
    get_storage,
    storage_config,
)

router = APIRouter(prefix="/admin", tags=["media"], dependencies=[Depends(require_staff)])
logger = logging.getLogger("mztlab.media")

# PIL format name -> (extension, MIME type). The admin can enable a subset of
# these through the upload settings; both lists are the validated allow-list.
IMAGE_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}
IMAGE_BY_EXTENSION = {
    extension: (pil_format, mime) for pil_format, (extension, mime) in IMAGE_FORMATS.items()
}
AUDIO_EXTENSIONS = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
}
# Extra files. Everything here is a download / document format; nothing that a
# browser could execute (no html, svg, js …) is part of the catalog.
FILE_FORMATS = {
    "pdf": "application/pdf",
    "zip": "application/zip",
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
    "json": "application/json",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
MAX_PIXELS = 48_000_000
# Technical ceiling for the configurable upload limit (the Settings model
# validates 1-200 as well; keep the two in sync).
MAX_UPLOAD_MB = 200
STREAM_CHUNK_BYTES = 1024 * 1024


# ---------------------------------------------------------------------------
# Response DTOs (kept next to the routes because the media payload is derived
# from `images.image_payload`; the API contract is generated from these)
# ---------------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MediaImageInfo(ImagePayload):
    """Read-only derivative metadata (mirror of `images.image_payload`)."""


class MediaOwnerInfo(_Model):
    id: int
    name: str
    username: str = ""


class MediaItemPayload(_Model):
    id: int
    filename: str
    original_name: str
    mime: str
    size: int
    width: int = 0
    height: int = 0
    alt: str = ""
    owner_id: int
    exif: ExifPayload | None = None
    placeholder: str = ""
    created_at: str
    owner: MediaOwnerInfo
    url: str
    kind: Literal["image", "audio", "file"]
    image: MediaImageInfo | None = None


class MediaUploadPayload(MediaItemPayload):
    exif_summary: str = ""


class MediaListPayload(Pagination):
    items: list[MediaItemPayload]


class OptimizeScopeIn(_Model):
    """Optional scope for `POST /media/optimize-all` (omit = every image)."""

    gallery_id: int | None = None


class JobQueuedPayload(_Model):
    ok: bool
    job_id: int


# ---------------------------------------------------------------------------
# Upload policy (typed settings, single source of truth)
# ---------------------------------------------------------------------------


def _enabled_image_formats(
    tokens: list[str],
) -> dict[str, tuple[str, str]]:
    selected = [token for token in tokens if token in IMAGE_BY_EXTENSION]
    # Never lock the admin out of uploading images: an empty/unknown selection
    # falls back to the full catalog.
    return {
        format_: IMAGE_BY_EXTENSION[format_] for format_ in (selected or list(IMAGE_BY_EXTENSION))
    }


def _enabled_audio_formats(tokens: list[str]) -> dict[str, str]:
    selected = [token for token in tokens if token in AUDIO_EXTENSIONS]
    return {
        extension: AUDIO_EXTENSIONS[extension] for extension in (selected or list(AUDIO_EXTENSIONS))
    }


def _enabled_file_formats(tokens: list[str]) -> dict[str, str]:
    # For extra files an explicit empty list means "no extra files", matching
    # the old explicit-empty setting semantics.
    return {extension: FILE_FORMATS[extension] for extension in tokens if extension in FILE_FORMATS}


def _upload_policy(
    settings: Settings | None = None,
) -> tuple[
    int,
    dict[str, tuple[str, str]],
    dict[str, str],
    dict[str, str],
]:
    """Read the size / format limits from the typed settings for one upload."""
    active = settings or load_settings()
    upload = active.upload
    max_mb = max(1, min(MAX_UPLOAD_MB, int(upload.max_mb)))
    return (
        max_mb * 1024 * 1024,
        _enabled_image_formats(list(upload.image_formats)),
        _enabled_audio_formats(list(upload.audio_formats)),
        _enabled_file_formats(list(upload.file_formats)),
    )


def _format_error(
    images: dict[str, tuple[str, str]],
    audio: dict[str, str],
    files: dict[str, str] | None = None,
) -> str:
    parts: list[str] = []
    if images:
        parts.append(" / ".join(format_.upper() for format_ in images) + " 图片")
    if audio:
        parts.append(" / ".join(ext.upper() for ext in audio) + " 音频")
    if files:
        parts.append(" / ".join(ext.upper() for ext in files) + " 文件")
    return "只支持 " + "，或 ".join(parts)


def _file_format(data: bytes, filename: str, allowed: dict[str, str]) -> tuple[str, str] | None:
    """Validate extra files by extension plus a light magic-byte check.

    `data` is only the first bytes of the file (the upload path never reads the
    whole file into memory); every signature below lives in the first bytes.
    """
    extension = Path(filename).suffix.lower().lstrip(".")
    mime = allowed.get(extension)
    if not mime:
        return None
    if extension == "pdf" and not data.startswith(b"%PDF"):
        return None
    if extension in {"zip", "docx", "xlsx", "pptx"} and not data.startswith(b"PK"):
        return None
    return extension, mime


def _any_file_format(filename: str) -> tuple[str, str]:
    """Administrator uploads may use any extension; keep it filesystem-safe."""
    name = Path(filename).name
    extension = re.sub(r"[^a-z0-9]+", "", Path(name).suffix.lower().lstrip("."))[:12]
    if not extension:
        extension = "bin"
    mime = (
        FILE_FORMATS.get(extension) or mimetypes.guess_type(name)[0] or "application/octet-stream"
    )
    return extension, mime


def _audio_format(data: bytes, filename: str, allowed: dict[str, str]) -> tuple[str, str] | None:
    """Validate the common audio containers by extension + magic bytes."""
    extension = Path(filename).suffix.lower().lstrip(".")
    mime = allowed.get(extension)
    if not mime:
        return None
    signatures = {
        "mp3": lambda b: (
            b.startswith(b"ID3") or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0)
        ),
        "m4a": lambda b: len(b) > 12 and b[4:8] == b"ftyp",
        "ogg": lambda b: b.startswith(b"OggS"),
        "oga": lambda b: b.startswith(b"OggS"),
        "wav": lambda b: b.startswith(b"RIFF") and b[8:12] == b"WAVE",
        "flac": lambda b: b.startswith(b"fLaC"),
    }
    signature = signatures.get(extension)
    return (extension, mime) if signature and signature(data) else None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

_MEDIA_SELECT = """
    SELECT m.*, u.display_name AS owner_name, u.username AS owner_username
    FROM media m
    LEFT JOIN users u ON u.id = m.owner_id
"""


def _media_url(filename: str) -> str:
    return f"/media/{filename}"


def _serialize(row: Any, settings: Settings | None = None) -> dict[str, Any]:
    item = dict(row)
    owner_id = item.get("owner_id")
    item["owner_id"] = owner_id
    item["owner"] = {
        "id": owner_id,
        "name": item.get("owner_name") or "未知成员",
        "username": item.get("owner_username") or "",
    }
    item["url"] = _media_url(str(item["filename"]))
    if str(item.get("mime", "")).startswith("audio/"):
        item["kind"] = "audio"
    elif str(item.get("mime", "")).startswith("image/"):
        item["kind"] = "image"
    else:
        item["kind"] = "file"
    item["exif"] = parse_stored(item.get("exif"))
    active_settings = settings or load_settings_cached()
    # The only derivative metadata the API exposes. `derivative_set` and
    # `source_sha1` are internal pointers/token inputs, not client data.
    item["image"] = image_payload(item, active_settings)
    item.pop("owner_name", None)
    item.pop("owner_username", None)
    item.pop("derivative_set", None)
    item.pop("source_sha1", None)
    return item


def _get_row(conn: Any, media_id: int) -> Any:
    row = conn.execute(_MEDIA_SELECT + " WHERE m.id = ?", (media_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文件不存在")
    return row


def _read_media_bytes(filename: str) -> bytes | None:
    """Read an original through the storage backend (local disk or bucket)."""
    try:
        return get_storage().read(filename)
    except (StorageError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Streamed upload
# ---------------------------------------------------------------------------


def _stream_upload_to_temp(file: UploadFile, max_bytes: int) -> tuple[Path, int, str]:
    """Copy the upload into a temp file in 1 MB chunks, hashing as it goes.

    Returns `(path, size, sha1_hex)`. Raises 400 for an empty file and 413 as
    soon as the limit is crossed, deleting the partial temp file in both cases.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path: Path | None = None
    size = 0
    digest = hashlib.sha1()
    try:
        with tempfile.NamedTemporaryFile(
            dir=UPLOAD_DIR, prefix=".upload-", suffix=".tmp", delete=False
        ) as handle:
            path = Path(handle.name)
            limit_mb = max(1, max_bytes // (1024 * 1024))
            while True:
                chunk = file.file.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413, detail=f"文件不能超过 {limit_mb}MB"
                    )
                digest.update(chunk)
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="文件为空")
    except HTTPException:
        # The handle is closed by the `with` block before this runs (Windows
        # cannot delete an open file).
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    if path is None:  # pragma: no cover - NamedTemporaryFile always names a file
        raise HTTPException(status_code=500, detail="临时文件创建失败")
    return path, size, digest.hexdigest()


def _read_header(path: Path, length: int = 64) -> bytes:
    with path.open("rb") as handle:
        return handle.read(length)


def _probe_image(
    path: Path,
    *,
    is_admin: bool,
    image_formats: dict[str, tuple[str, str]],
) -> tuple[str | None, int, int]:
    """Validate an image from the temp file and return `(PIL format, w, h)`.

    Returns `(None, 0, 0)` when the file is not an image; raises 415/413 for a
    recognised image that the policy rejects.
    """
    fmt: str | None = None
    try:
        with Image.open(path) as probe:
            candidate = (probe.format or "").upper()
            if candidate in IMAGE_FORMATS:
                extension = IMAGE_FORMATS[candidate][0]
                if not is_admin and extension not in image_formats:
                    raise HTTPException(
                        status_code=415,
                        detail=f"图片格式 {extension.upper()} 未启用",
                    )
                probe.verify()
                fmt = candidate
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return None, 0, 0

    if fmt is None:
        return None, 0, 0
    try:
        with Image.open(path) as image:
            width, height = image.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return None, 0, 0
    if width * height > MAX_PIXELS:
        raise HTTPException(status_code=413, detail="图片像素过大")
    return fmt, width, height


def _dominant_color(path: Path) -> str:
    """A 1×1 average colour used as a decode-time placeholder (from disk)."""
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            thumbnail = image.convert("RGB").resize((1, 1), Image.Resampling.LANCZOS)
            pixel = thumbnail.getpixel((0, 0))
            if not isinstance(pixel, tuple):
                return ""
            red, green, blue = pixel[:3]
            return f"#{red:02x}{green:02x}{blue:02x}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/media", response_model=MediaListPayload)
def list_media(
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    q: str | None = Query(None, max_length=100),
    kind: str | None = Query(None, pattern="^(image|audio|file)$"),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    where: list[str] = []
    args: list[Any] = []
    if q:
        where.append("(m.original_name LIKE ? OR m.alt LIKE ?)")
        needle = f"%{q}%"
        args.extend([needle, needle])
    if kind:
        where.append("m.mime LIKE ?")
        args.append(f"{kind}/%")
    if not can(user, "content.others"):
        where.append("m.owner_id = ?")
        args.append(int(user["id"]))
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with db() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM media m{clause}", args).fetchone()[0])
        rows = conn.execute(
            f"""{_MEDIA_SELECT}{clause}
                ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?""",
            [*args, per_page, (page - 1) * per_page],
        ).fetchall()
    return {
        "items": [_serialize(row) for row in rows],
        **pagination(page, per_page, total),
    }


@router.post("/media", status_code=201, response_model=MediaUploadPayload)
def upload_media(
    file: UploadFile = File(...),
    alt: str = Form(default=""),
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    """Streamed upload: temp file → validate → atomic move → row + prewarm job.

    Synchronous on purpose: `Pillow.verify()`, EXIF parsing and the storage write
    are CPU/IO heavy and must run in the thread pool, never on the event loop.
    """
    is_admin = str(user.get("role") or "") == "admin"
    max_bytes, image_formats, audio_formats, file_formats = _upload_policy()
    if is_admin:
        # Administrators bypass the configured size / format policy; only the
        # technical ceiling and image sanity checks remain.
        max_bytes = ADMIN_MAX_UPLOAD_BYTES

    temp_path, size, source_sha1 = _stream_upload_to_temp(file, max_bytes)
    try:
        fmt, width, height = _probe_image(
            temp_path, is_admin=is_admin, image_formats=image_formats
        )
        if fmt:
            ext, mime = IMAGE_FORMATS[fmt]
        else:
            header = _read_header(temp_path)
            audio = _audio_format(
                header,
                file.filename or "",
                AUDIO_EXTENSIONS if is_admin else audio_formats,
            )
            if audio:
                ext, mime = audio
                width = height = 0
            elif is_admin:
                ext, mime = _any_file_format(file.filename or "")
                width = height = 0
            else:
                extra = _file_format(header, file.filename or "", file_formats)
                if not extra:
                    raise HTTPException(
                        status_code=415,
                        detail=_format_error(image_formats, audio_formats, file_formats),
                    )
                ext, mime = extra
                width = height = 0

        exif = read_exif_file(temp_path) if fmt else None
        placeholder = _dominant_color(temp_path) if fmt else ""

        now = datetime.now(UTC)
        relative_dir = Path(f"{now.year:04d}") / f"{now.month:02d}"
        filename = f"{uuid.uuid4().hex}.{ext}"
        relative = (relative_dir / filename).as_posix()
        try:
            get_storage().save_file(relative, temp_path, mime)
        except StorageError as error:
            raise HTTPException(status_code=502, detail=f"媒体存储不可用：{error}") from error

        original_name = (file.filename or f"media.{ext}").replace("\\", "/").split("/")[-1][:200]
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO media(filename, original_name, mime, size, width, height,
                                     alt, owner_id, exif, source_sha1, placeholder, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    relative,
                    original_name,
                    mime,
                    size,
                    width,
                    height,
                    alt.strip()[:200],
                    int(user["id"]),
                    dump_exif(exif),
                    source_sha1,
                    placeholder,
                    now_iso(),
                ),
            )
            media_id = int(cursor.lastrowid or 0)
            row = _get_row(conn, media_id)
            item = _serialize(row)
        item["exif_summary"] = summary(exif)
        # Encoding happens in the background worker; the upload never waits for
        # AVIF/WebP generation (R4: read paths only assemble existing artifacts).
        if fmt:
            enqueue_job("prewarm", media_id=media_id)
        return item
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/media/{media_id}", response_model=MediaItemPayload)
def media_detail(media_id: int, user: dict = Depends(require_staff)) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        authorize(user, row, "write")
        return _serialize(row)


@router.put("/media/{media_id}/exif", response_model=MediaItemPayload)
def update_media_exif(
    media_id: int,
    payload: MediaExifIn,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        authorize(user, row, "write")
        if not str(row["mime"]).startswith("image/"):
            raise HTTPException(status_code=400, detail="音频文件没有 EXIF 信息")
        raw = _read_media_bytes(row["filename"])
        if raw is None:
            raise HTTPException(status_code=404, detail="原始图片文件不存在")
        current = parse_stored(row["exif"]) or {}
        incoming = {
            "camera": payload.camera.strip(),
            "lens": payload.lens.strip(),
            "taken_at": payload.taken_at.strip(),
            "aperture": payload.aperture.strip(),
            "exposure": payload.exposure.strip(),
            "iso": payload.iso,
            "focal_length": payload.focal_length.strip(),
            "focal_length_35mm": payload.focal_length_35mm,
        }
        labels = {
            "camera": "相机",
            "lens": "镜头",
            "taken_at": "拍摄时间",
            "aperture": "光圈",
            "exposure": "快门",
            "iso": "ISO",
            "focal_length": "焦距",
            "focal_length_35mm": "等效焦距",
        }
        conflicts = []
        merged = dict(incoming)
        for key, label in labels.items():
            existing = current.get(key)
            if existing in (None, "", 0):
                continue
            merged[key] = existing
            submitted = incoming.get(key)
            if submitted not in (None, "", 0) and str(submitted) != str(existing):
                conflicts.append(label)
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=f"已有 EXIF 不可修改：{'、'.join(conflicts)}",
            )
        exif = dict(current)
        exif.update(merged)
        exif["found"] = True
        if merged["taken_at"] and not exif.get("taken_at_raw"):
            exif["taken_at_raw"] = str(merged["taken_at"]).replace("-", ":")
        exif["iso"] = exif.get("iso") or None
        exif["focal_length_35mm"] = exif.get("focal_length_35mm") or None
        conn.execute("UPDATE media SET exif = ? WHERE id = ?", (dump_exif(exif), media_id))
        updated = _get_row(conn, media_id)
    return _serialize(updated)


@router.get("/media/{media_id}/exif", response_model=MediaExifResponse)
def media_exif(media_id: int, user: dict = Depends(require_staff)) -> dict[str, Any]:
    """Read EXIF from the original file, caching the result on the media row.

    Older uploads have no cached block; reading on demand means the feature
    works for images uploaded before the cached block existed.
    """
    with db() as conn:
        row = _get_row(conn, media_id)
        authorize(user, row, "write")
        stored = parse_stored(row["exif"])
        raw = _read_media_bytes(row["filename"]) if not stored else None
        fresh = None
        if raw:
            from ..exif import read_exif_bytes

            fresh = read_exif_bytes(raw)
        if fresh and not stored:
            conn.execute("UPDATE media SET exif = ? WHERE id = ?", (dump_exif(fresh), media_id))
        exif = stored or fresh
        source = "cache" if stored else "file" if fresh else "none"
    return {
        "media_id": media_id,
        "exif": exif,
        "source": source,
        "summary": summary(exif),
    }


def _media_patch_columns(row: Any, payload: MediaAltIn) -> dict[str, Any]:
    """Map only the fields the client actually sent to `media` columns.

    PATCH semantics: an omitted field keeps its current value. Per-image AVIF
    quality no longer exists (BC-34), so `alt` is the only editable field; old
    clients still sending `avif_quality*` are ignored rather than erroring.
    """
    provided = payload.model_dump(exclude_unset=True)
    columns: dict[str, Any] = {}
    if "alt" in provided:
        columns["alt"] = str(provided["alt"] or "")
    return columns


def _apply_media_columns(conn: Any, media_id: int, columns: dict[str, Any]) -> None:
    if not columns:
        return
    assignments = ", ".join(f"{name} = ?" for name in columns)
    conn.execute(
        f"UPDATE media SET {assignments} WHERE id = ?",
        [*columns.values(), media_id],
    )


@router.put("/media/{media_id}", response_model=MediaItemPayload)
@router.patch("/media/{media_id}", response_model=MediaItemPayload)
def update_media(
    media_id: int,
    payload: MediaAltIn,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    """Partial update: omitted fields are untouched."""
    with db() as conn:
        row = _get_row(conn, media_id)
        authorize(user, row, "write")
        columns = _media_patch_columns(row, payload)
        _apply_media_columns(conn, media_id, columns)
        updated = _get_row(conn, media_id)
    return _serialize(updated)


# ---------------------------------------------------------------------------
# Derivative / storage maintenance (jobs table, no in-process globals)
# ---------------------------------------------------------------------------


@router.post("/media/optimize-all", response_model=JobQueuedPayload)
def optimize_all(
    payload: OptimizeScopeIn | None = None,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    """Queue a `reencode` job for every image (or one gallery's images)."""
    scope = payload or OptimizeScopeIn()
    job_id = enqueue_job("reencode", gallery_id=scope.gallery_id, force=True)
    return {"ok": True, "job_id": job_id}


@router.post("/media/{media_id}/optimize", response_model=JobQueuedPayload)
def optimize_media(
    media_id: int,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    """Queue a `reencode` job for one image."""
    with db() as conn:
        row = _get_row(conn, media_id)
        authorize(user, row, "write")
        if not is_image_row(row):
            raise HTTPException(status_code=400, detail="只有图片可以优化")
    job_id = enqueue_job("reencode", media_id=media_id, force=True)
    return {"ok": True, "job_id": job_id}


@router.get("/storage/status", response_model=StorageStatusResponse)
def storage_status(
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    config = storage_config()
    reachable: bool | None = None
    error = ""
    health: dict[str, Any] | None = None
    try:
        # Works for local, S3 and MirrorStorage alike; never reaches into a
        # backend-specific client from the route.
        health = get_storage().health()
        reachable = bool(health.get("ok", True))
    except Exception as exception:
        reachable = False
        error = str(exception)
    return {
        "config": config.describe(),
        "avif": AVIF_SUPPORTED,
        "webp": WEBP_SUPPORTED,
        "reachable": reachable,
        "error": error,
        "health": health,
        "derivatives": derivative_stats(),
    }


@router.post("/storage/test", response_model=StorageTestResponse)
def storage_test(
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    storage = get_storage()
    key = f"_probe/{uuid.uuid4().hex}.txt"
    try:
        storage.save(key, b"mztlab-storage-probe", "text/plain")
        matched = storage.read(key) == b"mztlab-storage-probe"
        storage.delete(key)
    except Exception as error:
        return {"ok": False, "message": f"连接失败：{error}"}
    return {
        "ok": matched,
        "backend": storage_config().backend,
        "message": "存储连接正常" if matched else "读写结果不一致",
    }


@router.post("/storage/sync", response_model=JobQueuedPayload)
def storage_sync(
    payload: StorageSyncIn,
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    """Queue a `storage_sync` job (force-upload local files to the bucket).

    The connectivity/config pre-check stays synchronous so a misconfigured
    bucket is a 400 instead of a failed background job; the upload itself runs
    in the worker and its progress lives on the `jobs` row.
    """
    if get_remote_storage() is None:
        raise HTTPException(
            status_code=400,
            detail="请先在「图片与存储」填写对象存储的 bucket 与 endpoint（无需先切换存储后端）",
        )
    job_id = enqueue_job(
        "storage_sync",
        force=payload.force,
        payload={"force": payload.force, "scope": payload.scope},
    )
    return {"ok": True, "job_id": job_id}


@router.delete("/media/{media_id}", response_model=MediaDeleteResponse)
def delete_media(
    media_id: int, user: dict = Depends(require_permission("media.manage"))
) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        authorize(user, row, "write")
        filename = row["filename"]
    delete_derivatives(media_id)
    # A missing object must not stop the database row from being removed.
    with contextlib.suppress(StorageError):
        get_storage().delete(filename)
    with db() as conn:
        conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    return {"ok": True, "deleted": media_id}

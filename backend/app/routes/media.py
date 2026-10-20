"""Media library: validated image/audio uploads, ownership, EXIF, listing, deletion.

Every file has an owner: the member who uploaded it. Admins can see and manage
the whole library; editors and authors only see their own files unless the site
owner enables 设置 → 协作与权限 → 编辑可管理他人内容.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from PIL import Image, UnidentifiedImageError

from ..config import ADMIN_MAX_UPLOAD_BYTES
from ..db import db, load_settings, load_settings_cached, now_iso
from ..defaults import (
    UPLOAD_AUDIO_FORMATS,
    UPLOAD_FILE_FORMATS,
    UPLOAD_IMAGE_FORMATS,
)
from ..deps import require_permission, require_staff
from ..exif import dump_exif, parse_stored, read_exif_bytes, summary
from ..images import (
    AVIF_SUPPORTED,
    WEBP_SUPPORTED,
    delete_derivatives,
    derivative_stats,
    dominant_color,
    image_payload,
    is_image_row,
    prewarm_media,
)
from ..permissions import can, owns
from ..posts import pagination
from ..schemas import MediaAltIn, MediaExifIn, StorageSyncIn
from ..storage import (
    LocalStorage,
    StorageError,
    get_remote_storage,
    get_storage,
    storage_config,
)
from ..storage_sync import sync_local_to_remote

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
    extension: (pil_format, mime)
    for pil_format, (extension, mime) in IMAGE_FORMATS.items()
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
MAX_UPLOAD_MB = 200


def _parse_formats(raw: Any, allowed: tuple[str, ...]) -> list[str]:
    tokens = {
        token.strip().lower().lstrip(".")
        for token in str(raw or "").replace(";", ",").split(",")
    }
    selected = [format_ for format_ in allowed if format_ in tokens]
    # Never lock the admin out of uploading: an empty selection falls back to
    # the full allow-list.
    return selected or list(allowed)


def _upload_policy() -> tuple[
    int,
    dict[str, tuple[str, str]],
    dict[str, str],
    dict[str, str],
]:
    """Read the size / format limits from settings for the current upload."""
    settings = load_settings()
    try:
        max_mb = max(1, min(MAX_UPLOAD_MB, int(settings.get("upload_max_mb", 12))))
    except (TypeError, ValueError):
        max_mb = 12
    image_formats = _parse_formats(settings.get("upload_image_formats"), UPLOAD_IMAGE_FORMATS)
    audio_formats = _parse_formats(settings.get("upload_audio_formats"), UPLOAD_AUDIO_FORMATS)
    raw_files = settings.get("upload_file_formats")
    # An explicit empty value means "no extra files"; missing/unknown tokens
    # fall back to the default catalog so a typo cannot silently lock uploads.
    file_formats = (
        _parse_formats(raw_files, UPLOAD_FILE_FORMATS)
        if str(raw_files or "").strip()
        else []
    )
    images = {
        format_: IMAGE_BY_EXTENSION[format_]
        for format_ in image_formats
        if format_ in IMAGE_BY_EXTENSION
    }
    audio = {ext: mime for ext, mime in AUDIO_EXTENSIONS.items() if ext in audio_formats}
    files = {ext: mime for ext, mime in FILE_FORMATS.items() if ext in file_formats}
    return max_mb * 1024 * 1024, images, audio, files


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
    """Validate extra files by extension plus a light magic-byte check."""
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
        FILE_FORMATS.get(extension)
        or mimetypes.guess_type(name)[0]
        or "application/octet-stream"
    )
    return extension, mime


def _audio_format(data: bytes, filename: str, allowed: dict[str, str]) -> tuple[str, str] | None:
    """Validate the common audio containers by extension + magic bytes."""
    extension = Path(filename).suffix.lower().lstrip(".")
    mime = allowed.get(extension)
    if not mime:
        return None
    signatures = {
        "mp3": lambda b: b.startswith(b"ID3")
        or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0),
        "m4a": lambda b: len(b) > 12 and b[4:8] == b"ftyp",
        "ogg": lambda b: b.startswith(b"OggS"),
        "oga": lambda b: b.startswith(b"OggS"),
        "wav": lambda b: b.startswith(b"RIFF") and b[8:12] == b"WAVE",
        "flac": lambda b: b.startswith(b"fLaC"),
    }
    signature = signatures.get(extension)
    return (extension, mime) if signature and signature(data) else None

_MEDIA_SELECT = """
    SELECT m.*, COALESCE(m.owner_id, m.uploaded_by) AS effective_owner_id,
           u.display_name AS owner_name, u.username AS owner_username
    FROM media m
    LEFT JOIN users u ON u.id = COALESCE(m.owner_id, m.uploaded_by)
"""


def _media_url(filename: str) -> str:
    return f"/media/{filename}"


def _serialize(row: sqlite3.Row, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    item = dict(row)
    owner_id = item.get("owner_id") or item.get("uploaded_by")
    item["owner_id"] = owner_id
    item["owner"] = {
        "id": owner_id,
        "name": item.get("owner_name") or "未知成员",
        "username": item.get("owner_username") or "",
    }
    item["url"] = _media_url(item["filename"])
    if str(item.get("mime", "")).startswith("audio/"):
        item["kind"] = "audio"
    elif str(item.get("mime", "")).startswith("image/"):
        item["kind"] = "image"
    else:
        item["kind"] = "file"
    item["exif"] = parse_stored(item.get("exif"))
    active_settings = settings or load_settings_cached()
    item["image"] = image_payload(item, active_settings)
    item.pop("ready_hash", None)
    item.pop("effective_owner_id", None)
    item.pop("owner_name", None)
    item.pop("owner_username", None)
    return item


def _get_row(conn: sqlite3.Connection, media_id: int) -> sqlite3.Row:
    row = conn.execute(_MEDIA_SELECT + " WHERE m.id = ?", (media_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="文件不存在")
    return row


def _ensure_owner(user: dict[str, Any], row: sqlite3.Row) -> None:
    if can(user, "content.others") or owns(user, row):
        return
    raise HTTPException(status_code=403, detail="只能管理自己上传的媒体")


def _read_media_bytes(filename: str) -> bytes | None:
    """Read an original through the storage backend (local disk or bucket)."""
    try:
        return get_storage().read(filename)
    except (StorageError, FileNotFoundError):
        return None


@router.get("/media")
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
        where.append("COALESCE(m.owner_id, m.uploaded_by) = ?")
        args.append(int(user["id"]))
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with db() as conn:
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM media m{clause}", args).fetchone()[0]
        )
        rows = conn.execute(
            f"""{_MEDIA_SELECT}{clause}
                ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?""",
            [*args, per_page, (page - 1) * per_page],
        ).fetchall()
    return {
        "items": [_serialize(row) for row in rows],
        **pagination(page, per_page, total),
    }


@router.post("/media", status_code=201)
async def upload_media(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    alt: str = Form(default=""),
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    is_admin = str(user.get("role") or "") == "admin"
    max_bytes, image_formats, audio_formats, file_formats = _upload_policy()
    if is_admin:
        # Administrators bypass the configured size / format policy; only the
        # technical ceiling and image sanity checks remain.
        max_bytes = ADMIN_MAX_UPLOAD_BYTES
    data = await file.read(max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"文件不能超过 {limit_mb}MB",
        )

    fmt: str | None = None
    width = height = 0
    try:
        with Image.open(BytesIO(data)) as probe:
            candidate = (probe.format or "").upper()
            if candidate in IMAGE_FORMATS:
                ext = IMAGE_FORMATS[candidate][0]
                if not is_admin and ext not in image_formats:
                    raise HTTPException(
                        status_code=415,
                        detail=f"图片格式 {ext.upper()} 未启用：{_format_error(image_formats, audio_formats, file_formats)}",
                    )
                probe.verify()
                with Image.open(BytesIO(data)) as image:
                    width, height = image.size
                    if width * height > MAX_PIXELS:
                        raise HTTPException(status_code=413, detail="图片像素过大")
                fmt = candidate
    except HTTPException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        fmt = None

    if fmt:
        ext, mime = IMAGE_FORMATS[fmt]
    else:
        audio = _audio_format(
            data,
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
            extra = _file_format(data, file.filename or "", file_formats)
            if not extra:
                raise HTTPException(
                    status_code=415,
                    detail=_format_error(image_formats, audio_formats, file_formats),
                )
            ext, mime = extra
            width = height = 0

    now = datetime.now(timezone.utc)
    relative_dir = Path(f"{now.year:04d}") / f"{now.month:02d}"
    filename = f"{uuid.uuid4().hex}.{ext}"
    relative = (relative_dir / filename).as_posix()
    storage = get_storage()
    try:
        storage.save(relative, data, mime)
    except StorageError as error:
        raise HTTPException(status_code=502, detail=f"媒体存储不可用：{error}") from error

    # Pillow is only for images; EXIF never blocks an otherwise valid upload.
    exif = read_exif_bytes(data) if fmt else None
    original_name = (file.filename or f"media.{ext}").replace("\\", "/").split("/")[-1][:200]
    placeholder = dominant_color(data) if fmt else ""
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO media(filename, original_name, mime, size, width, height,
                                 alt, uploaded_by, owner_id, exif, placeholder, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                relative,
                original_name,
                mime,
                len(data),
                width,
                height,
                alt.strip()[:200],
                int(user["id"]),
                int(user["id"]),
                dump_exif(exif),
                placeholder,
                now_iso(),
            ),
        )
        media_id = int(cur.lastrowid)
        row = _get_row(conn, media_id)
        item = _serialize(row)
    item["exif_summary"] = summary(exif)
    # Generate the scene variants in the background; the upload itself must not
    # wait for AVIF encoding. Until the set is complete the API serves proxy
    # URLs instead of direct object-storage URLs.
    if fmt and load_settings_cached().get("image_prewarm", True):
        background.add_task(prewarm_media, media_id)
    return item


@router.get("/media/optimize-status")
def optimize_status(
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    with _OPTIMIZE_LOCK:
        return dict(_OPTIMIZE_STATE)


@router.get("/media/{media_id}")
def media_detail(
    media_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        _ensure_owner(user, row)
        return _serialize(row)


@router.put("/media/{media_id}/exif")
def update_media_exif(
    media_id: int,
    payload: MediaExifIn,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        _ensure_owner(user, row)
        if not str(row["mime"]).startswith("image/"):
            raise HTTPException(status_code=400, detail="音频文件没有 EXIF 信息")
        raw = _read_media_bytes(row["filename"])
        if raw is None:
            raise HTTPException(status_code=404, detail="原始图片文件不存在")
        current = parse_stored(row["exif"]) or read_exif_bytes(raw) or {}
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
        conn.execute(
            "UPDATE media SET exif = ? WHERE id = ?", (dump_exif(exif), media_id)
        )
        updated = _get_row(conn, media_id)
    return _serialize(updated)


@router.get("/media/{media_id}/exif")
def media_exif(
    media_id: int, user: dict = Depends(require_staff)
) -> dict[str, Any]:
    """Read EXIF from the original file, caching the result on the media row.

    Older uploads have no cached block; reading on demand means the feature
    works for images uploaded before this route existed.
    """
    with db() as conn:
        row = _get_row(conn, media_id)
        _ensure_owner(user, row)
        stored = parse_stored(row["exif"])
        raw = _read_media_bytes(row["filename"]) if not stored else None
        fresh = read_exif_bytes(raw) if raw else None
        if fresh and not stored:
            conn.execute(
                "UPDATE media SET exif = ? WHERE id = ?", (dump_exif(fresh), media_id)
            )
        exif = stored or fresh
        source = "cache" if stored else "file" if fresh else "none"
    return {
        "media_id": media_id,
        "exif": exif,
        "source": source,
        "summary": summary(exif),
    }


@router.put("/media/{media_id}")
def update_media(
    media_id: int,
    payload: MediaAltIn,
    background: BackgroundTasks,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        _ensure_owner(user, row)
        conn.execute(
            "UPDATE media SET alt = ? WHERE id = ?", (payload.alt, media_id)
        )
        if is_image_row(row) and (
            payload.avif_quality_auto is not None or payload.avif_quality is not None
        ):
            # Explicit auto/manual switch: `avif_quality` is only meaningful in
            # manual mode, so always keep a valid 1-100 value in the column.
            auto = (
                (1 if payload.avif_quality_auto else 0)
                if payload.avif_quality_auto is not None
                else int(row["avif_quality_auto"] or 0)
            )
            manual = (
                payload.avif_quality
                if payload.avif_quality is not None
                else int(row["avif_quality"] or 0)
            )
            if not 1 <= int(manual or 0) <= 100:
                manual = 55
            # A changed quality produces a new URL token; drop the "ready" mark
            # so the API falls back to proxy URLs until the new set is built.
            conn.execute(
                """UPDATE media SET avif_quality_auto = ?, avif_quality = ?,
                          ready_hash = '' WHERE id = ?""",
                (auto, int(manual), media_id),
            )
            if load_settings_cached().get("image_prewarm", True):
                background.add_task(prewarm_media, media_id)
        updated = _get_row(conn, media_id)
    return _serialize(updated)


# ---------------------------------------------------------------------------
# Derivative / storage maintenance
# ---------------------------------------------------------------------------

_OPTIMIZE_STATE: dict[str, Any] = {
    "running": False,
    "total": 0,
    "done": 0,
    "failed": 0,
    "started_at": "",
    "finished_at": "",
    "error": "",
}
_OPTIMIZE_LOCK = threading.Lock()


def _run_optimize_all() -> None:
    with _OPTIMIZE_LOCK:
        _OPTIMIZE_STATE.update(
            running=True, total=0, done=0, failed=0, error="",
            started_at=now_iso(), finished_at="",
        )
    try:
        with db() as conn:
            ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM media WHERE mime LIKE 'image/%' ORDER BY id"
                )
            ]
        with _OPTIMIZE_LOCK:
            _OPTIMIZE_STATE["total"] = len(ids)
        for media_id in ids:
            try:
                prewarm_media(media_id)
            except Exception:
                with _OPTIMIZE_LOCK:
                    _OPTIMIZE_STATE["failed"] += 1
                continue
            with _OPTIMIZE_LOCK:
                _OPTIMIZE_STATE["done"] += 1
    except Exception as error:  # pragma: no cover - defensive
        with _OPTIMIZE_LOCK:
            _OPTIMIZE_STATE["error"] = str(error)
    finally:
        with _OPTIMIZE_LOCK:
            _OPTIMIZE_STATE["running"] = False
            _OPTIMIZE_STATE["finished_at"] = now_iso()


@router.post("/media/optimize-all")
def optimize_all(
    background: BackgroundTasks,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    with _OPTIMIZE_LOCK:
        if _OPTIMIZE_STATE["running"]:
            return {"ok": True, "started": False, "message": "已有优化任务在进行"}
    background.add_task(_run_optimize_all)
    return {"ok": True, "started": True}


@router.post("/media/{media_id}/optimize")
def optimize_media(
    media_id: int,
    background: BackgroundTasks,
    user: dict = Depends(require_permission("media.manage")),
) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        _ensure_owner(user, row)
        if not is_image_row(row):
            raise HTTPException(status_code=400, detail="只有图片可以优化")
    background.add_task(prewarm_media, media_id, True)
    return {"ok": True, "queued": True, "media_id": media_id}


@router.get("/storage/status")
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


@router.post("/storage/test")
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


# ---------------------------------------------------------------------------
# Force-sync local files to object storage
# ---------------------------------------------------------------------------

_SYNC_STATE: dict[str, Any] = {
    "running": False,
    "total": 0,
    "uploaded": 0,
    "skipped": 0,
    "failed": 0,
    "bytes": 0,
    "current": "",
    "force": False,
    "scope": "all",
    "started_at": "",
    "finished_at": "",
    "error": "",
    "errors": [],
}
_SYNC_LOCK = threading.Lock()


def _sync_progress(result) -> None:
    with _SYNC_LOCK:
        _SYNC_STATE.update(
            total=result.total,
            uploaded=result.uploaded,
            skipped=result.skipped,
            failed=result.failed,
            bytes=result.bytes_uploaded,
            current=result.current,
            errors=result.errors[-5:],
        )


def _run_storage_sync(force: bool, scope: str) -> None:
    with _SYNC_LOCK:
        _SYNC_STATE.update(
            running=True, total=0, uploaded=0, skipped=0, failed=0, bytes=0,
            current="", force=force, scope=scope, error="", errors=[],
            started_at=now_iso(), finished_at="",
        )
    try:
        remote = get_remote_storage()
        if remote is None:
            raise StorageError("对象存储未配置（请填写 bucket 与 endpoint）")
        result = sync_local_to_remote(
            LocalStorage(),
            remote,
            force=force,
            scope=scope,
            progress=_sync_progress,
        )
        with _SYNC_LOCK:
            _SYNC_STATE.update(
                total=result.total,
                uploaded=result.uploaded,
                skipped=result.skipped,
                failed=result.failed,
                bytes=result.bytes_uploaded,
                errors=result.errors[-5:],
            )
    except Exception as error:  # pragma: no cover - defensive
        logger.exception("storage sync failed")
        with _SYNC_LOCK:
            _SYNC_STATE["error"] = str(error)
    finally:
        with _SYNC_LOCK:
            _SYNC_STATE["running"] = False
            _SYNC_STATE["current"] = ""
            _SYNC_STATE["finished_at"] = now_iso()


@router.get("/storage/sync-status")
def storage_sync_status(
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    with _SYNC_LOCK:
        return dict(_SYNC_STATE)


@router.post("/storage/sync")
def storage_sync(
    payload: StorageSyncIn,
    background: BackgroundTasks,
    user: dict = Depends(require_permission("settings.manage")),
) -> dict[str, Any]:
    """Force-upload local originals and/or cached derivatives to the bucket.

    Runs in the background; poll `/api/admin/storage/sync-status` for progress.
    """
    remote = get_remote_storage()
    if remote is None:
        raise HTTPException(
            status_code=400,
            detail="请先在「图片与存储」填写对象存储的 bucket 与 endpoint（无需先切换存储后端）",
        )
    with _SYNC_LOCK:
        if _SYNC_STATE["running"]:
            return {
                "ok": True,
                "started": False,
                "message": "已有同步任务在进行",
            }
    background.add_task(_run_storage_sync, payload.force, payload.scope)
    return {
        "ok": True,
        "started": True,
        "force": payload.force,
        "scope": payload.scope,
    }


@router.delete("/media/{media_id}")
def delete_media(
    media_id: int, user: dict = Depends(require_permission("media.manage"))
) -> dict[str, Any]:
    with db() as conn:
        row = _get_row(conn, media_id)
        _ensure_owner(user, row)
        filename = row["filename"]
    delete_derivatives(media_id)
    try:
        get_storage().delete(filename)
    except StorageError:
        # A missing object must not stop the database row from being removed.
        pass
    with db() as conn:
        conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    return {"ok": True, "deleted": media_id}

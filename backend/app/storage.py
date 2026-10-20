"""Storage abstraction: local disk (default) or S3-compatible object storage.

Cloudflare R2 is the reference S3 target: it is configured from the admin panel
(设置 → 图片与存储) and stored in the settings table, with environment
variables as a fallback for containerised deployments. Secrets never leave the
process; see `routes/admin.py` for the masking of the admin settings response.

The rest of the application only ever deals with relative keys:

* originals          `2026/05/{uuid}.jpg`
* generated variants `_derived/{media_id}/{hash}/{scene}/{width}.{ext}`
"""

from __future__ import annotations

import logging
import mimetypes
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol

from .config import IMAGE_CACHE_DIR, S3_ENV_FALLBACK, S3_PATH_STYLE_ENV, UPLOAD_DIR

logger = logging.getLogger("mztlab.storage")

DERIVED_PREFIX = "_derived/"
DERIVED_CACHE_CONTROL = "public, max-age=31536000, immutable"
ORIGINAL_CACHE_CONTROL = "public, max-age=604800"


class StorageError(RuntimeError):
    """Storage backend could not complete the operation."""


class StorageMissing(StorageError):
    """The requested key does not exist."""


def content_type_for(key: str) -> str:
    extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    known = {
        "avif": "image/avif",
        "webp": "image/webp",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
        "oga": "audio/ogg",
        "wav": "audio/wav",
        "flac": "audio/flac",
        "pdf": "application/pdf",
        "zip": "application/zip",
        "txt": "text/plain",
        "md": "text/markdown",
        "csv": "text/csv",
        "json": "application/json",
    }
    return known.get(extension) or mimetypes.guess_type(key)[0] or "application/octet-stream"


@dataclass(frozen=True)
class StorageConfig:
    backend: str
    serve_mode: str
    public_base_url: str
    endpoint: str
    bucket: str
    region: str
    access_key: str
    secret_key: str
    prefix: str
    path_style: bool
    # Keep a local copy of every object written to the bucket (see MirrorStorage).
    backup_local: bool = False

    @property
    def is_s3(self) -> bool:
        return self.backend == "s3"

    @property
    def direct_enabled(self) -> bool:
        """True when generated files can be fetched straight from the bucket."""
        return (
            self.is_s3
            and bool(self.bucket)
            and bool(self.public_base_url)
            and self.serve_mode in {"auto", "direct"}
        )

    def signature(self) -> tuple[Any, ...]:
        return (
            self.backend, self.serve_mode, self.public_base_url, self.endpoint,
            self.bucket, self.region, self.access_key, self.secret_key,
            self.prefix, self.path_style, self.backup_local,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "serve_mode": self.serve_mode,
            "bucket": self.bucket,
            "endpoint": self.endpoint,
            "region": self.region,
            "prefix": self.prefix,
            "path_style": self.path_style,
            "public_base_url": self.public_base_url,
            "direct_enabled": self.direct_enabled,
            "backup_local": self.backup_local,
            "secret_configured": bool(self.secret_key),
        }


class Storage(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> None: ...
    def read(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def public_url(self, key: str) -> str | None: ...
    def derived_base(self, media_id: int, token: str) -> str | None: ...
    def local_path(self, key: str) -> Path | None: ...
    def stream(self, key: str) -> Iterator[bytes]: ...
    def health(self) -> dict[str, Any]: ...
    def size(self, key: str) -> int: ...


class LocalStorage:
    """Files live under UPLOAD_DIR (originals) and IMAGE_CACHE_DIR (variants)."""

    def __init__(self) -> None:
        self.upload_dir = UPLOAD_DIR
        self.cache_dir = IMAGE_CACHE_DIR

    def _root(self, key: str) -> Path:
        # `_derived` (prefix cleanup) and `_derived/...` (an object) both live in
        # the derivative cache; everything else is an original upload.
        derived_root = DERIVED_PREFIX.rstrip("/")
        is_derived = key == derived_root or key.startswith(DERIVED_PREFIX)
        return self.cache_dir if is_derived else self.upload_dir

    def local_path(self, key: str) -> Path:
        root = self._root(key).resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root):
            raise StorageError("非法存储路径")
        return path

    def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace so a reader never sees a half-written derivative.
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def read(self, key: str) -> bytes:
        path = self.local_path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise StorageMissing(key) from error

    def exists(self, key: str) -> bool:
        try:
            return self.local_path(key).is_file()
        except StorageError:
            return False

    def delete(self, key: str) -> None:
        try:
            self.local_path(key).unlink()
        except FileNotFoundError:
            return

    def delete_prefix(self, prefix: str) -> int:
        root = self._root(prefix).resolve()
        base = (root / prefix).resolve()
        if not base.is_relative_to(root) or not base.exists():
            return 0
        removed = 0
        if base.is_file():
            base.unlink(missing_ok=True)
            return 1
        for child in sorted(base.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink(missing_ok=True)
                removed += 1
            else:
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            base.rmdir()
        except OSError:
            pass
        return removed

    def public_url(self, key: str) -> str | None:
        return None

    def derived_base(self, media_id: int, token: str) -> str | None:
        return None

    def stream(self, key: str) -> Iterator[bytes]:
        raise StorageError("local storage serves files through local_path()")

    def health(self) -> dict[str, Any]:
        if not self.upload_dir.exists() or not self.cache_dir.exists():
            raise StorageError("本地数据目录不存在")
        return {"ok": True, "backend": "local"}

    def size(self, key: str) -> int:
        path = self.local_path(key)
        try:
            return path.stat().st_size
        except FileNotFoundError as error:
            raise StorageMissing(key) from error

    def iter_keys(self, scope: str = "all") -> Iterator[str]:
        """Walk originals and/or generated derivatives currently on disk.

        Used by the "force sync local cache to remote" maintenance action.
        Temporary files and hidden files are ignored.
        """
        roots: list[tuple[Path, str]] = []
        if scope in {"all", "originals"}:
            roots.append((self.upload_dir, "originals"))
        if scope in {"all", "derivatives"}:
            roots.append((self.cache_dir, "derivatives"))
        for root, kind in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                name = path.name
                if name.startswith(".") or name.endswith(".tmp"):
                    continue
                relative = path.relative_to(root).as_posix()
                if not relative or ".." in relative:
                    continue
                if kind == "originals" and relative.startswith(DERIVED_PREFIX):
                    # Derivatives live in their own root; never double-count.
                    continue
                yield relative


class S3Storage:
    """S3-compatible bucket storage (Cloudflare R2 by default)."""

    def __init__(self, config: StorageConfig) -> None:
        self.config = config
        self._client: Any = None
        self._lock = threading.Lock()

    # -- client ---------------------------------------------------------
    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                import boto3
                from botocore.client import Config as BotoConfig
            except ImportError as error:  # pragma: no cover - installation issue
                raise StorageError(
                    "对象存储需要 boto3：请先安装后端依赖（requirements.txt）"
                ) from error
            if not self.config.bucket:
                raise StorageError("对象存储未配置 bucket")
            if not self.config.endpoint and not self.config.region:
                raise StorageError("对象存储未配置 endpoint 或 region")
            addressing = "path" if self.config.path_style else "virtual"
            self._client = boto3.client(
                "s3",
                endpoint_url=self.config.endpoint or None,
                region_name=self.config.region or None,
                aws_access_key_id=self.config.access_key or None,
                aws_secret_access_key=self.config.secret_key or None,
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={"addressing_style": addressing},
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
            return self._client

    def _key(self, key: str) -> str:
        prefix = self.config.prefix.strip("/")
        return f"{prefix}/{key}" if prefix else key

    # -- operations -----------------------------------------------------
    def save(self, key: str, data: bytes, content_type: str) -> None:
        cache = DERIVED_CACHE_CONTROL if key.startswith(DERIVED_PREFIX) else ORIGINAL_CACHE_CONTROL
        try:
            self.client.put_object(
                Bucket=self.config.bucket,
                Key=self._key(key),
                Body=data,
                ContentType=content_type,
                CacheControl=cache,
            )
        except StorageError:
            raise
        except Exception as error:  # boto3 exceptions are not imported at module level
            raise StorageError(f"对象存储写入失败：{error}") from error

    def read(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=self._key(key))
            return response["Body"].read()
        except Exception as error:
            if _is_missing(error):
                raise StorageMissing(key) from error
            raise StorageError(f"对象存储读取失败：{error}") from error

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.config.bucket, Key=self._key(key))
            return True
        except StorageError:
            raise
        except Exception as error:
            if _is_missing(error):
                return False
            raise StorageError(f"对象存储查询失败：{error}") from error

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.config.bucket, Key=self._key(key))
        except Exception as error:
            raise StorageError(f"对象存储删除失败：{error}") from error

    def delete_prefix(self, prefix: str) -> int:
        removed = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.config.bucket, Prefix=self._key(prefix)):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if not keys:
                continue
            self.client.delete_objects(
                Bucket=self.config.bucket, Delete={"Objects": keys, "Quiet": True}
            )
            removed += len(keys)
        return removed

    def public_url(self, key: str) -> str | None:
        base = self.config.public_base_url.strip().rstrip("/")
        if not base:
            return None
        return f"{base}/{self._key(key)}"

    def derived_base(self, media_id: int, token: str) -> str | None:
        if not self.config.direct_enabled:
            return None
        return self.public_url(f"{DERIVED_PREFIX}{media_id}/{token}")

    def local_path(self, key: str) -> Path | None:
        return None

    def stream(self, key: str) -> Iterator[bytes]:
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=self._key(key))
        except Exception as error:
            if _is_missing(error):
                raise StorageMissing(key) from error
            raise StorageError(f"对象存储读取失败：{error}") from error
        return response["Body"].iter_chunks(chunk_size=64 * 1024)

    def presigned_url(self, key: str, expires: int = 300) -> str | None:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.config.bucket, "Key": self._key(key)},
                ExpiresIn=expires,
            )
        except Exception:
            return None

    def health(self) -> dict[str, Any]:
        """Cheap connectivity probe used by the admin storage status card."""
        if not self.config.bucket:
            raise StorageError("未配置 bucket")
        try:
            self.client.head_bucket(Bucket=self.config.bucket)
        except StorageError:
            raise
        except Exception as error:
            raise StorageError(f"无法连接对象存储：{error}") from error
        return {"ok": True, "backend": "s3", "bucket": self.config.bucket}

    def size(self, key: str) -> int:
        try:
            response = self.client.head_object(
                Bucket=self.config.bucket, Key=self._key(key)
            )
            return int(response.get("ContentLength", -1))
        except Exception as error:
            if _is_missing(error):
                raise StorageMissing(key) from error
            raise StorageError(f"对象存储查询失败：{error}") from error


def _is_missing(error: Exception) -> bool:
    code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
    return code in {"NoSuchKey", "404", "NotFound", "NoSuchBucket"}


def _iter_file(path: Path):
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            yield chunk


class MirrorStorage:
    """Object-storage primary with a best-effort local copy.

    The primary backend stays authoritative for reads; the local copy is a
    disaster-recovery backup and makes switching back to `local` painless.
    Backup failures are logged but never fail the request, and a missing
    primary object falls back to the local copy when it still exists.
    """

    def __init__(self, primary: Storage, backup: Storage) -> None:
        self.primary = primary
        self.backup = backup

    @property
    def client(self) -> Any:
        """Expose the primary client (probes/scripts use it directly)."""
        client = getattr(self.primary, "client", None)
        if client is None:
            raise StorageError("当前存储后端没有可用的 S3 客户端")
        return client

    @property
    def config(self) -> Any:
        return getattr(self.primary, "config", None)

    def health(self) -> dict[str, Any]:
        result = dict(self.primary.health())
        result["backup_local"] = True
        try:
            self.backup.health()
        except StorageError as error:
            # The primary is what matters for serving; report the backup issue.
            result["backup_ok"] = False
            result["backup_error"] = str(error)
        else:
            result["backup_ok"] = True
        return result

    def size(self, key: str) -> int:
        return self.primary.size(key)

    def save(self, key: str, data: bytes, content_type: str) -> None:
        self.primary.save(key, data, content_type)
        try:
            self.backup.save(key, data, content_type)
        except Exception:
            logger.warning("local backup write failed for %s", key, exc_info=True)

    def read(self, key: str) -> bytes:
        try:
            return self.primary.read(key)
        except StorageMissing:
            return self.backup.read(key)

    def exists(self, key: str) -> bool:
        try:
            if self.primary.exists(key):
                return True
        except StorageError:
            logger.warning("primary storage unavailable while checking %s", key)
        return self.backup.exists(key)

    def delete(self, key: str) -> None:
        try:
            self.primary.delete(key)
        except StorageError as error:
            logger.warning("primary delete failed for %s: %s", key, error)
        self.backup.delete(key)

    def delete_prefix(self, prefix: str) -> int:
        removed = 0
        try:
            removed = self.primary.delete_prefix(prefix)
        except StorageError as error:
            logger.warning("primary prefix delete failed for %s: %s", prefix, error)
        self.backup.delete_prefix(prefix)
        return removed

    def public_url(self, key: str) -> str | None:
        return self.primary.public_url(key)

    def derived_base(self, media_id: int, token: str) -> str | None:
        return self.primary.derived_base(media_id, token)

    def local_path(self, key: str) -> Path | None:
        return self.primary.local_path(key)

    def stream(self, key: str) -> Iterator[bytes]:
        try:
            return self.primary.stream(key)
        except StorageMissing:
            path = self.backup.local_path(key)
            if path is not None and path.is_file():
                return _iter_file(path)
            raise

    def presigned_url(self, key: str, expires: int = 300) -> str | None:
        presign = getattr(self.primary, "presigned_url", None)
        return presign(key, expires) if presign else None

    def backup_path(self, key: str) -> Path | None:
        """Local copy location, if the backup backend is local."""
        return self.backup.local_path(key)



def _pick(settings: dict[str, Any], key: str) -> str:
    value = settings.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return (S3_ENV_FALLBACK.get(key) or "").strip()


def storage_config() -> StorageConfig:
    try:
        from .db import load_settings_cached

        settings: dict[str, Any] = load_settings_cached()
    except Exception:  # database not ready (first import / tests)
        settings = {}
    backend = (
        (S3_ENV_FALLBACK.get("storage_backend") or "").strip().lower()
        or _pick(settings, "storage_backend").lower()
        or "local"
    )
    if backend not in {"local", "s3"}:
        backend = "local"
    serve_mode = str(settings.get("storage_serve_mode") or "auto").lower()
    if serve_mode not in {"auto", "proxy", "direct"}:
        serve_mode = "auto"
    path_style = settings.get("storage_s3_path_style")
    path_style = S3_PATH_STYLE_ENV if path_style is None else bool(path_style)
    return StorageConfig(
        backend=backend,
        serve_mode=serve_mode,
        public_base_url=_pick(settings, "storage_public_base_url"),
        endpoint=_pick(settings, "storage_s3_endpoint"),
        bucket=_pick(settings, "storage_s3_bucket"),
        region=_pick(settings, "storage_s3_region") or "auto",
        access_key=_pick(settings, "storage_s3_access_key"),
        secret_key=_pick(settings, "storage_s3_secret_key"),
        prefix=_pick(settings, "storage_s3_prefix") or "mztlab",
        path_style=path_style,
        backup_local=bool(settings.get("storage_backup_local", False)),
    )


_STORAGE_CACHE: tuple[tuple[Any, ...], Storage] | None = None
_STORAGE_LOCK = threading.Lock()


def get_storage() -> Storage:
    """Return the configured backend, rebuilding it when settings change."""
    global _STORAGE_CACHE
    config = storage_config()
    signature = config.signature()
    with _STORAGE_LOCK:
        if _STORAGE_CACHE is not None and _STORAGE_CACHE[0] == signature:
            return _STORAGE_CACHE[1]
        if config.is_s3:
            primary: Storage = S3Storage(config)
            storage: Storage = (
                MirrorStorage(primary, LocalStorage())
                if config.backup_local
                else primary
            )
        else:
            storage = LocalStorage()
        _STORAGE_CACHE = (signature, storage)
        return storage


def reset_storage() -> None:
    """Drop the cached backend instance (called after settings are saved)."""
    global _STORAGE_CACHE
    with _STORAGE_LOCK:
        _STORAGE_CACHE = None


def get_remote_storage() -> "S3Storage | None":
    """Build a direct S3 client for sync/migration tasks.

    Does not require `storage_backend=s3`: as long as a bucket (and an
    endpoint/region) is configured, the admin can push local files to the
    bucket while the site is still served from disk.
    """
    config = storage_config()
    if not config.bucket:
        return None
    if not config.endpoint and not config.region:
        return None
    return S3Storage(config)

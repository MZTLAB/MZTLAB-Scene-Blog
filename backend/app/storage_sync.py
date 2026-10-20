"""Force-sync local media files to the configured object storage.

This is the "upload everything that is on disk" counterpart to the normal
write-through path: useful after switching `storage_backend` from `local` to
`s3`, restoring a bucket, or repairing a partially lost remote.

Only local files are considered:
* `UPLOAD_DIR` → original uploads
* `IMAGE_CACHE_DIR` → generated AVIF/WebP/JPEG derivatives (`_derived/…`)

With `force=False` an object is uploaded only when it is missing remotely or its
size differs; `force=True` overwrites every remote object.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from .storage import LocalStorage, content_type_for

logger = logging.getLogger("mztlab.storage_sync")

SCOPES = {"all", "originals", "derivatives"}
MAX_ERRORS = 20


@dataclass
class SyncResult:
    total: int = 0
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_uploaded: int = 0
    current: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "uploaded": self.uploaded,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_uploaded": self.bytes_uploaded,
            "current": self.current,
            "errors": list(self.errors),
        }


def local_objects(local: LocalStorage, scope: str = "all") -> list[tuple[str, int]]:
    """Return `(key, size)` for the files the sync would consider."""
    items: list[tuple[str, int]] = []
    for key in local.iter_keys(scope):
        try:
            items.append((key, local.size(key)))
        except Exception:  # vanished between listing and stat
            continue
    return items


def sync_local_to_remote(
    local: LocalStorage,
    remote,
    *,
    force: bool = False,
    scope: str = "all",
    progress: Callable[[SyncResult], None] | None = None,
) -> SyncResult:
    """Upload local objects to `remote`. Never raises for a single bad file."""
    if scope not in SCOPES:
        raise ValueError(f"未知同步范围：{scope}")
    objects = local_objects(local, scope)
    result = SyncResult(total=len(objects))
    for key, size in objects:
        result.current = key
        try:
            if not force:
                try:
                    if remote.exists(key) and remote.size(key) == size:
                        result.skipped += 1
                        if progress:
                            progress(result)
                        continue
                except Exception:
                    # A flaky HEAD should not abort the sync; try the upload.
                    pass
            data = local.read(key)
            remote.save(key, data, content_type_for(key))
            result.uploaded += 1
            result.bytes_uploaded += len(data)
        except Exception as error:
            result.failed += 1
            message = f"{key}: {error}"
            if len(result.errors) < MAX_ERRORS:
                result.errors.append(message)
            logger.warning("storage sync failed for %s: %s", key, error)
        if progress:
            progress(result)
    result.current = ""
    return result

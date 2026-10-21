"""Admin jobs API (BC-15).

One endpoint family replaces the retired per-feature progress routes
(`/media/optimize-status`, `/storage/sync-status`): create a job, list jobs,
read one job, cancel a queued job. The worker lives in `app.jobs`; these routes
only write/read the `jobs` table.

Permissions are per kind: image maintenance needs `media.manage`, storage/rebuild
need `settings.manage`, data export needs `data.export`. `rebuild_site` is
reserved (R5): creating it is allowed and `GET` returns it as `queued`, but the
worker never claims it.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ..api.models import JobStatusResponse
from ..db import db
from ..deps import require_staff
from ..jobs import (
    JOB_KINDS,
    JOB_STATUSES,
    RESERVED_KINDS,
    cancel_job,
    enqueue_job,
    get_job,
    list_jobs,
)
from ..permissions import can

logger = logging.getLogger("mztlab.jobs.api")

router = APIRouter(prefix="/admin", tags=["jobs"], dependencies=[Depends(require_staff)])

JobKind = Literal[
    "prewarm",
    "reencode",
    "gc_derivatives",
    "rerender_content",
    "storage_sync",
    "export",
    "rebuild_site",
]
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]

# Kind -> the permission that may enqueue it. `export` is the specific
# `data.export` capability (editors hold it without `settings.manage`).
KIND_PERMISSIONS: dict[str, str] = {
    "prewarm": "media.manage",
    "reencode": "media.manage",
    "gc_derivatives": "media.manage",
    "rerender_content": "media.manage",
    "storage_sync": "settings.manage",
    "rebuild_site": "settings.manage",
    "export": "data.export",
}

# request body field shape; mirrors `schemas.JobCreateIn` plus the required kind
class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: JobKind
    media_id: int | None = None
    gallery_id: int | None = None
    force: bool = False


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class JobListResponse(_Model):
    items: list[JobStatusResponse]
    total: int


class JobActionResponse(_Model):
    ok: bool
    job: JobStatusResponse


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    return dict(job)


def _require_kind_permission(user: dict[str, Any], kind: str) -> None:
    permission = KIND_PERMISSIONS.get(kind)
    if permission is None:
        raise HTTPException(status_code=400, detail="未知任务类型")
    if not can(user, permission):
        raise HTTPException(status_code=403, detail="当前角色没有这项权限")


@router.post("/jobs", status_code=201, response_model=JobActionResponse)
def create_job(
    payload: JobCreateRequest,
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    """Enqueue one job; the response is the persisted row (status `queued`)."""
    _require_kind_permission(user, payload.kind)
    if payload.kind == "prewarm" and payload.media_id is None:
        raise HTTPException(status_code=422, detail="prewarm 任务需要 media_id")
    if payload.media_id is not None:
        with db() as conn:
            if not conn.execute("SELECT 1 FROM media WHERE id = ?", (payload.media_id,)).fetchone():
                raise HTTPException(status_code=404, detail="文件不存在")
    job_id = enqueue_job(
        payload.kind,
        media_id=payload.media_id,
        gallery_id=payload.gallery_id,
        force=payload.force,
    )
    job = get_job(job_id)
    if job is None:  # pragma: no cover - insert just happened
        raise HTTPException(status_code=500, detail="任务创建失败")
    return {"ok": True, "job": _job_payload(job)}


@router.get("/jobs", response_model=JobListResponse)
def jobs_list(
    status: JobStatus | None = Query(None),
    kind: JobKind | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    """List jobs, newest first, optionally filtered by status/kind."""
    if not can(user, "media.manage") and not can(user, "settings.manage") and not can(
        user, "data.export"
    ):
        raise HTTPException(status_code=403, detail="当前角色没有这项权限")
    items, total = list_jobs(status=status, kind=kind, limit=limit)
    return {"items": [_job_payload(item) for item in items], "total": total}


@router.get("/jobs/kinds", include_in_schema=False)
def job_kinds(user: dict = Depends(require_staff)) -> dict[str, Any]:
    """Small helper used by the admin UI; not part of the frozen contract."""
    return {
        "kinds": list(JOB_KINDS),
        "statuses": list(JOB_STATUSES),
        "reserved": sorted(RESERVED_KINDS),
    }


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_detail(job_id: int, user: dict = Depends(require_staff)) -> dict[str, Any]:
    """Poll one job (replaces the retired `optimize-status`/`sync-status`)."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _job_payload(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobActionResponse)
def cancel(
    job_id: int,
    user: dict = Depends(require_staff),
) -> dict[str, Any]:
    """Cancel a *queued* job.

    A `running` job cannot be cancelled (409): the worker is mid-handler and
    there is no safe cancellation point, so the API says so instead of faking
    it. Cancelled jobs stay queryable with `status='cancelled'`.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_kind_permission(user, str(job["kind"]))
    updated, cancelled = cancel_job(job_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not cancelled:
        raise HTTPException(status_code=409, detail="只能取消排队中的任务")
    return {"ok": True, "job": updated}

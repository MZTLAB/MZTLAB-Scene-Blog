"""Persistent background jobs (3.0.0).

The `jobs` table replaces the 2.x in-process `_OPTIMIZE_STATE` / `_SYNC_STATE`
dictionaries: progress, retries and cancellation survive a restart, and every
maintenance action has a stable job id the admin UI can poll (BC-15 / ADR-7).

Design:

* **One worker thread per process**, started from the FastAPI lifespan
  (`app.main.lifespan`). The API and the worker talk only through the database,
  so splitting the worker into its own process later needs no business change.
* **Atomic claim**: a single `UPDATE ... RETURNING` both selects the next queued
  row and marks it `running`, so two workers can never pick the same job.
* **Heartbeat + recovery**: the worker refreshes `heartbeat_at` every few
  seconds. `recover_stale_jobs()` (run at worker start) puts `running` rows with
  an expired heartbeat back to `queued` until `attempts >= MAX_ATTEMPTS`, then
  fails them with "heartbeat timeout".
* **Queue isolation**: the claim orders by an explicit per-kind priority so a
  long `reencode` cannot starve interactive `prewarm` work. `rebuild_site` is
  reserved and is *never* claimed in this version (R5): its rows stay `queued`
  forever so the future executor only has to be plugged in.
* **Cancellation** is honest: only `queued` rows can be cancelled (the API
  returns 409 for `running`). A running handler checks `check_cancelled()`
  between batches; because nothing outside can flip a running row to
  `cancelled` today, that check only fires if a future feature adds it.

Job kinds:

``prewarm``        generate one image's artifact set (payload ``media_id``)
``reencode``       force-regenerate a scope (media / gallery / all images),
                   then enqueue one ``rerender_content``
``rerender_content`` re-render published posts whose Markdown references media
``gc_derivatives`` delete derivative rows/objects no longer referenced
``storage_sync``   force-upload local originals/derivatives to the bucket
``export``         reserved: executor lands in a later phase (job completes with
                   a "reserved" result, it does not fail the worker)
``rebuild_site``   reserved: never claimed in 3.0.0 (stays ``queued``)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import db, now_iso

logger = logging.getLogger("mztlab.jobs")

# Status machine: queued -> running -> done | failed ; queued -> cancelled.
JOB_STATUSES: tuple[str, ...] = ("queued", "running", "done", "failed", "cancelled")
JOB_KINDS: tuple[str, ...] = (
    "prewarm",
    "reencode",
    "gc_derivatives",
    "rerender_content",
    "storage_sync",
    "export",
    "rebuild_site",
)
# Reserved kinds: accepted by the API but never executed in 3.0.0.
RESERVED_KINDS: frozenset[str] = frozenset({"rebuild_site"})

# Per-kind polling priority: interactive work first, bulk maintenance last.
# This `CASE` is the queue-isolation implementation (see module docstring).
CLAIM_ORDER_CASE = """CASE kind
        WHEN 'prewarm' THEN 0
        WHEN 'reencode' THEN 1
        WHEN 'rerender_content' THEN 2
        WHEN 'gc_derivatives' THEN 3
        WHEN 'storage_sync' THEN 4
        ELSE 5
    END"""

# The claim; `rebuild_site` is explicitly excluded so reserved rows stay queued.
CLAIM_SQL = f"""
    UPDATE jobs
       SET status = 'running',
           started_at = ?,
           heartbeat_at = ?,
           attempts = attempts + 1
     WHERE id = (
           SELECT id FROM jobs
            WHERE status = 'queued' AND kind NOT IN ('rebuild_site')
            ORDER BY {CLAIM_ORDER_CASE}, id
            LIMIT 1
     )
    RETURNING *
"""

STALE_HEARTBEAT_SECONDS = 60
MAX_ATTEMPTS = 3
HEARTBEAT_SECONDS = 5
POLL_SECONDS = 1.0
MAX_ERROR_LENGTH = 2000


class JobCancelled(RuntimeError):
    """The job was cancelled; the worker records the final status."""


# ---------------------------------------------------------------------------
# Enqueue / query helpers
# ---------------------------------------------------------------------------


def _build_payload(
    *,
    media_id: int | None,
    gallery_id: int | None,
    force: bool,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    data: dict[str, Any] = dict(payload or {})
    if media_id is not None:
        data["media_id"] = int(media_id)
    if gallery_id is not None:
        data["gallery_id"] = int(gallery_id)
    if force:
        data["force"] = True
    return data


def enqueue_job(
    kind: str,
    *,
    media_id: int | None = None,
    gallery_id: int | None = None,
    force: bool = False,
    payload: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Insert one `queued` job and return its id.

    Pass `conn` when the caller already owns a short transaction (for example
    the demo seeder); otherwise this opens and commits its own transaction.
    Enqueuing never executes the handler inline.
    """
    if kind not in JOB_KINDS:
        raise ValueError(f"未知任务类型：{kind}")
    data = _build_payload(
        media_id=media_id, gallery_id=gallery_id, force=force, payload=payload
    )
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    created = now_iso()

    def _insert(connection: sqlite3.Connection) -> int:
        cursor = connection.execute(
            """INSERT INTO jobs(kind, payload, status, created_at)
               VALUES (?, ?, 'queued', ?)""",
            (kind, encoded, created),
        )
        return int(cursor.lastrowid or 0)

    if conn is not None:
        return _insert(conn)
    with db() as connection:
        return _insert(connection)


def enqueue_prewarm(
    media_id: int, *, conn: sqlite3.Connection | None = None
) -> int:
    """Convenience wrapper used by the upload path and the demo seeder."""
    return enqueue_job("prewarm", media_id=media_id, conn=conn)


def payload_of(job: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    raw = job["payload"] if not isinstance(job, dict) else job.get("payload")
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def get_job(job_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row is not None else None


def list_jobs(
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    args: list[Any] = []
    if status:
        where.append("status = ?")
        args.append(status)
    if kind:
        where.append("kind = ?")
        args.append(kind)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with db() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM jobs{clause}", args).fetchone()[0])
        rows = conn.execute(
            f"SELECT * FROM jobs{clause} ORDER BY id DESC LIMIT ?",
            [*args, max(1, min(int(limit), 200))],
        ).fetchall()
    return [dict(row) for row in rows], total


def cancel_job(job_id: int) -> tuple[dict[str, Any] | None, bool]:
    """Cancel a *queued* job.

    Returns ``(job, cancelled)``. A `running` job is never silently abandoned:
    the API maps that to a 409. A job that already finished is returned
    unchanged with ``cancelled=False``.
    """
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None, False
        if row["status"] != "queued":
            return dict(row), False
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ?",
            (now_iso(), job_id),
        )
        updated = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return (dict(updated) if updated is not None else None), True


# ---------------------------------------------------------------------------
# Claim / lifecycle
# ---------------------------------------------------------------------------


def claim_next_job() -> dict[str, Any] | None:
    """Atomically claim the highest-priority queued job (or return None)."""
    stamp = now_iso()
    with db() as conn:
        row = conn.execute(CLAIM_SQL, (stamp, stamp)).fetchone()
    if row is None:
        return None
    return dict(row)


def heartbeat(job_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (now_iso(), job_id)
        )


def set_progress(job_id: int, progress: int) -> None:
    value = max(0, min(100, int(progress)))
    with db() as conn:
        conn.execute("UPDATE jobs SET progress = ? WHERE id = ?", (value, job_id))


def mark_done(job_id: int, result: dict[str, Any] | None = None) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE jobs SET status = 'done', progress = 100, result = ?,
                   error = '', finished_at = ?
               WHERE id = ?""",
            (_json(result) if result else "", now_iso(), job_id),
        )


def mark_failed(job_id: int, error: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
            (str(error)[:MAX_ERROR_LENGTH], now_iso(), job_id),
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def recover_stale_jobs(
    *,
    stale_seconds: int = STALE_HEARTBEAT_SECONDS,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, int]:
    """Requeue (or fail) `running` jobs whose worker stopped heartbeating.

    Called once at worker start. A crash therefore never leaves a job stuck in
    `running`: it is retried up to `max_attempts`, then failed explicitly.
    """
    cutoff = _iso_ago(stale_seconds)
    with db() as conn:
        rows = conn.execute(
            """SELECT id, attempts FROM jobs
               WHERE status = 'running'
                 AND (heartbeat_at IS NULL OR heartbeat_at < ?)""",
            (cutoff,),
        ).fetchall()
        requeued = 0
        failed = 0
        stamp = now_iso()
        for row in rows:
            if int(row["attempts"]) >= max_attempts:
                conn.execute(
                    """UPDATE jobs SET status = 'failed',
                           error = 'heartbeat timeout', finished_at = ?
                       WHERE id = ?""",
                    (stamp, row["id"]),
                )
                failed += 1
            else:
                conn.execute(
                    """UPDATE jobs SET status = 'queued', started_at = NULL,
                           heartbeat_at = NULL
                       WHERE id = ?""",
                    (row["id"],),
                )
                requeued += 1
    if requeued or failed:
        logger.warning(
            "recovered stale jobs: requeued=%s failed=%s", requeued, failed
        )
    return {"requeued": requeued, "failed": failed}


def _iso_ago(seconds: int) -> str:
    moment = datetime.now(UTC) - timedelta(seconds=max(0, int(seconds)))
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def check_cancelled(job_id: int) -> None:
    """Raise `JobCancelled` when the job row is no longer `running`.

    Long handlers call this between batches. Today only `queued` jobs can be
    cancelled (the API rejects cancelling a running job), so this is a
    forward-compatible guard rather than a hidden side channel.
    """
    with db() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None or row["status"] != "running":
        raise JobCancelled(f"job {job_id} is no longer running")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _scope_media_ids(payload: dict[str, Any]) -> list[int]:
    """Resolve which image media a `reencode` job targets."""
    media_id = payload.get("media_id")
    gallery_id = payload.get("gallery_id")
    with db() as conn:
        if media_id:
            row = conn.execute(
                "SELECT id FROM media WHERE id = ? AND mime LIKE 'image/%'",
                (int(media_id),),
            ).fetchone()
            return [int(row["id"])] if row else []
        if gallery_id:
            rows = conn.execute(
                """SELECT DISTINCT m.id FROM photos ph
                   JOIN media m ON m.id = ph.media_id
                   WHERE ph.gallery_id = ? AND m.mime LIKE 'image/%'
                   ORDER BY m.id""",
                (int(gallery_id),),
            ).fetchall()
            return [int(row["id"]) for row in rows]
        rows = conn.execute(
            "SELECT id FROM media WHERE mime LIKE 'image/%' ORDER BY id"
        ).fetchall()
    return [int(row["id"]) for row in rows]


def _handle_prewarm(job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    from . import images

    media_id = int(payload.get("media_id") or 0)
    if media_id <= 0:
        raise ValueError("prewarm 任务需要 media_id")
    ready = images.prewarm_media(media_id, force=bool(payload.get("force")))
    return {"media_id": media_id, "ready": bool(ready)}


def _handle_reencode(job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    from . import images

    job_id = int(job["id"])
    media_ids = _scope_media_ids(payload)
    if not media_ids:
        raise ValueError("没有可重编码的图片")
    reencoded = 0
    for index, media_id in enumerate(media_ids, start=1):
        check_cancelled(job_id)
        if images.prewarm_media(media_id, force=True):
            reencoded += 1
        set_progress(job_id, int(index * 100 / len(media_ids)))
    rerender_id = enqueue_job("rerender_content")
    return {
        "media": len(media_ids),
        "reencoded": reencoded,
        "rerender_job_id": rerender_id,
    }


def _handle_rerender_content(
    job: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    from .content import render_markdown
    from .images import rewrite_inline_images

    render_version: int | None = None
    try:
        from .services.content_admin import RENDER_PIPELINE_VERSION as _pipeline_version

        render_version = int(_pipeline_version)
    except ImportError:  # pragma: no cover - keeps the job usable if moved
        render_version = None

    job_id = int(job["id"])
    with db() as conn:
        rows = conn.execute(
            """SELECT id, content_md FROM posts
               WHERE status = 'published' AND content_md LIKE '%/media/%'
               ORDER BY id"""
        ).fetchall()
    post_ids = [int(row["id"]) for row in rows]
    updated = 0
    for index, post_id in enumerate(post_ids, start=1):
        check_cancelled(job_id)
        with db() as conn:
            row = conn.execute(
                "SELECT content_md FROM posts WHERE id = ?", (post_id,)
            ).fetchone()
            if row is None:
                continue
            html = rewrite_inline_images(render_markdown(str(row["content_md"] or "")), conn)
            if render_version is not None:
                conn.execute(
                    """UPDATE posts SET content_html = ?, render_version = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    (html, render_version, now_iso(), post_id),
                )
            else:
                conn.execute(
                    "UPDATE posts SET content_html = ?, updated_at = ? WHERE id = ?",
                    (html, now_iso(), post_id),
                )
        updated += 1
        set_progress(job_id, int(index * 100 / len(post_ids)))
    return {"posts": len(post_ids), "updated": updated}


def _handle_gc_derivatives(
    job: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    from . import images

    limit = int(payload.get("limit") or 200)
    stats = images.gc_derivatives(limit)
    return {"limit": limit, "deleted_rows": stats.get("rows", 0),
            "deleted_objects": stats.get("objects", 0)}


def _handle_storage_sync(
    job: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    from .storage import LocalStorage, StorageError, get_remote_storage
    from .storage_sync import sync_local_to_remote

    job_id = int(job["id"])
    force = bool(payload.get("force"))
    scope = str(payload.get("scope") or "all")
    remote = get_remote_storage()
    if remote is None:
        raise StorageError("对象存储未配置（请填写 bucket 与 endpoint）")

    last_progress = {"value": -1}

    def progress(result: Any) -> None:
        if not result.total:
            return
        value = int((result.uploaded + result.skipped + result.failed) * 100 / result.total)
        if value != last_progress["value"]:
            last_progress["value"] = value
            set_progress(job_id, value)

    result = sync_local_to_remote(
        LocalStorage(), remote, force=force, scope=scope, progress=progress
    )
    return {"force": force, "scope": scope, **result.as_dict()}


def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    """Run one claimed job's handler and return its JSON result."""
    kind = str(job["kind"])
    payload = payload_of(job)
    if kind == "prewarm":
        return _handle_prewarm(job, payload)
    if kind == "reencode":
        return _handle_reencode(job, payload)
    if kind == "rerender_content":
        return _handle_rerender_content(job, payload)
    if kind == "gc_derivatives":
        return _handle_gc_derivatives(job, payload)
    if kind == "storage_sync":
        return _handle_storage_sync(job, payload)
    if kind == "export":
        # Reserved: the executor lands in a later phase. Completing with a
        # clear marker keeps the worker healthy and the UI honest.
        return {
            "reserved": True,
            "detail": "export 执行器将在后续版本实现，本任务未执行导出",
        }
    if kind == "rebuild_site":
        # Never claimed by `claim_next_job`; defensive only (R5).
        return {
            "reserved": True,
            "detail": "rebuild_site 执行器尚未实现，本任务保持 queued",
        }
    raise ValueError(f"未知任务类型：{kind}")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class _Heartbeat:
    """Refresh `jobs.heartbeat_at` while a long handler runs."""

    def __init__(self, job_id: int, interval: float = HEARTBEAT_SECONDS) -> None:
        self.job_id = job_id
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"jobs-heartbeat-{self.job_id}", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                heartbeat(self.job_id)
            except Exception:  # pragma: no cover - defensive
                logger.warning("heartbeat failed for job %s", self.job_id, exc_info=True)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _process_claimed(job: dict[str, Any]) -> None:
    job_id = int(job["id"])
    beat = _Heartbeat(job_id)
    beat.start()
    try:
        result = execute_job(job)
    except JobCancelled:
        logger.info("job %s was cancelled while running", job_id)
        mark_done(job_id, {"cancelled": True})
    except Exception as error:
        logger.exception("job %s (%s) failed", job_id, job["kind"])
        mark_failed(job_id, str(error) or error.__class__.__name__)
    else:
        mark_done(job_id, result)
    finally:
        beat.stop()


def run_once() -> bool:
    """Claim and execute at most one job. Returns True when work was done."""
    job = claim_next_job()
    if job is None:
        return False
    _process_claimed(job)
    return True


class JobWorker:
    """The single background consumer started from the FastAPI lifespan."""

    def __init__(
        self,
        *,
        poll_seconds: float = POLL_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        stale_seconds: int = STALE_HEARTBEAT_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.stale_seconds = stale_seconds
        self.max_attempts = max_attempts
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        recover_stale_jobs(
            stale_seconds=self.stale_seconds, max_attempts=self.max_attempts
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jobs-worker", daemon=True)
        self._thread.start()
        logger.info("jobs worker started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("jobs worker did not stop within %.1fs", timeout)
        self._thread = None
        logger.info("jobs worker stopped")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- loop -----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = run_once()
            except Exception:  # pragma: no cover - defensive: never kill the thread
                logger.exception("jobs worker loop error")
                worked = False
            if not worked:
                self._stop.wait(self.poll_seconds)


_WORKER: JobWorker | None = None
_WORKER_LOCK = threading.Lock()


def start_worker() -> JobWorker:
    """Start the process-wide worker (idempotent)."""
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = JobWorker()
        _WORKER.start()
        return _WORKER


def stop_worker() -> None:
    """Stop the process-wide worker (idempotent; safe when never started)."""
    global _WORKER
    with _WORKER_LOCK:
        worker = _WORKER
        _WORKER = None
    if worker is not None:
        worker.stop()


__all__ = [
    "JOB_KINDS",
    "JOB_STATUSES",
    "RESERVED_KINDS",
    "JobCancelled",
    "JobWorker",
    "cancel_job",
    "check_cancelled",
    "claim_next_job",
    "enqueue_job",
    "enqueue_prewarm",
    "execute_job",
    "get_job",
    "list_jobs",
    "mark_done",
    "mark_failed",
    "payload_of",
    "recover_stale_jobs",
    "run_once",
    "set_progress",
    "start_worker",
    "stop_worker",
]

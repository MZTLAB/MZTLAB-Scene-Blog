"""Jobs table: enqueue, atomic claim, ordering, recovery, cancellation, API.

The background thread is disabled in tests (`BLOG_DISABLE_JOBS_WORKER=1` in
conftest); these tests drive `jobs.run_once()` / `jobs.claim_next_job()`
explicitly so every assertion is deterministic.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.db import db
from tests.conftest import admin_headers, setup_site


@pytest.fixture(autouse=True)
def clean_jobs(client: TestClient):
    with db() as conn:
        conn.execute("DELETE FROM jobs")
    yield
    with db() as conn:
        conn.execute("DELETE FROM jobs")


def _job_row(job_id: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    return dict(row)


def _set_heartbeat(job_id: int, value: str | None) -> None:
    with db() as conn:
        conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (value, job_id))


class EnqueueClaimTests:
    def test_enqueue_writes_a_queued_row(self) -> None:
        job_id = jobs.enqueue_job("prewarm", media_id=12)
        row = _job_row(job_id)
        assert row["kind"] == "prewarm"
        assert row["status"] == "queued"
        assert json.loads(row["payload"]) == {"media_id": 12}
        assert row["attempts"] == 0
        assert row["created_at"]

    def test_unknown_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            jobs.enqueue_job("not-a-kind")

    def test_claim_is_atomic_and_never_claims_twice(self) -> None:
        job_id = jobs.enqueue_job("prewarm", media_id=1)
        claimed = jobs.claim_next_job()
        assert claimed is not None
        assert claimed["id"] == job_id
        assert claimed["status"] == "running"
        assert claimed["attempts"] == 1
        assert claimed["started_at"]
        assert claimed["heartbeat_at"]
        # The row is no longer queued, so a second worker gets nothing.
        assert jobs.claim_next_job() is None

    def test_claim_returns_none_on_an_empty_queue(self) -> None:
        assert jobs.claim_next_job() is None

    def test_per_kind_ordering_is_polling_priority(self) -> None:
        # Insert in reverse priority order; claims must follow the CASE order.
        for kind in (
            "export",
            "storage_sync",
            "gc_derivatives",
            "rerender_content",
            "reencode",
            "prewarm",
        ):
            jobs.enqueue_job(kind)
        claimed = []
        while (job := jobs.claim_next_job()) is not None:
            claimed.append(job["kind"])
        assert claimed == [
            "prewarm",
            "reencode",
            "rerender_content",
            "gc_derivatives",
            "storage_sync",
            "export",
        ]


class ReservedKindTests:
    def test_rebuild_site_is_never_claimed_and_stays_queued(self) -> None:
        job_id = jobs.enqueue_job("rebuild_site")
        assert jobs.claim_next_job() is None
        assert jobs.run_once() is False
        assert _job_row(job_id)["status"] == "queued"

    def test_rebuild_site_api_shape(self, client: TestClient) -> None:
        setup_site(client)
        created = client.post(
            "/api/admin/jobs",
            json={"kind": "rebuild_site"},
            headers=admin_headers(),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["ok"] is True
        assert body["job"]["kind"] == "rebuild_site"
        assert body["job"]["status"] == "queued"
        job_id = body["job"]["id"]

        detail = client.get(f"/api/admin/jobs/{job_id}", headers=admin_headers())
        assert detail.status_code == 200
        assert detail.json()["status"] == "queued"

        listing = client.get(
            "/api/admin/jobs", params={"kind": "rebuild_site"}, headers=admin_headers()
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 1
        assert listing.json()["items"][0]["id"] == job_id


class RecoveryTests:
    def test_stale_running_job_is_requeued_while_attempts_remain(self) -> None:
        job_id = jobs.enqueue_job("prewarm", media_id=3)
        claimed = jobs.claim_next_job()
        assert claimed is not None
        _set_heartbeat(job_id, "2000-01-01T00:00:00Z")
        stats = jobs.recover_stale_jobs()
        assert stats == {"requeued": 1, "failed": 0}
        row = _job_row(job_id)
        assert row["status"] == "queued"
        assert row["started_at"] is None
        assert row["heartbeat_at"] is None
        assert row["attempts"] == 1

    def test_stale_job_with_three_attempts_fails_with_heartbeat_timeout(self) -> None:
        job_id = jobs.enqueue_job("prewarm", media_id=3)
        jobs.claim_next_job()
        with db() as conn:
            conn.execute(
                "UPDATE jobs SET attempts = 3, heartbeat_at = NULL WHERE id = ?",
                (job_id,),
            )
        stats = jobs.recover_stale_jobs()
        assert stats == {"requeued": 0, "failed": 1}
        row = _job_row(job_id)
        assert row["status"] == "failed"
        assert row["error"] == "heartbeat timeout"
        assert row["finished_at"]

    def test_fresh_running_job_is_left_alone(self) -> None:
        jobs.enqueue_job("prewarm", media_id=3)
        jobs.claim_next_job()
        assert jobs.recover_stale_jobs() == {"requeued": 0, "failed": 0}


class CancelTests:
    def test_cancel_queued_job(self) -> None:
        job_id = jobs.enqueue_job("prewarm", media_id=1)
        updated, cancelled = jobs.cancel_job(job_id)
        assert cancelled is True
        assert updated is not None
        assert updated["status"] == "cancelled"
        assert updated["finished_at"]
        assert jobs.claim_next_job() is None

    def test_running_job_cannot_be_cancelled(self) -> None:
        job_id = jobs.enqueue_job("prewarm", media_id=1)
        jobs.claim_next_job()
        updated, cancelled = jobs.cancel_job(job_id)
        assert cancelled is False
        assert updated is not None
        assert updated["status"] == "running"

    def test_cancel_api_rejects_a_running_job_with_409(self, client: TestClient) -> None:
        setup_site(client)
        created = client.post(
            "/api/admin/jobs",
            json={"kind": "prewarm", "media_id": 1},
            headers=admin_headers(),
        )
        # media_id 1 does not exist yet -> the API validates it first.
        assert created.status_code == 404
        # Insert a valid media row through the DB so the route accepts the job.
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO media(filename, original_name, mime, size, alt,
                                     owner_id, created_at)
                   VALUES ('2026/05/x.jpg', 'x.jpg', 'image/jpeg', 1, '', 1,
                           '2026-01-01T00:00:00Z')"""
            )
            media_id = int(cursor.lastrowid or 0)
        created = client.post(
            "/api/admin/jobs",
            json={"kind": "prewarm", "media_id": media_id},
            headers=admin_headers(),
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["job"]["id"]
        claimed = jobs.claim_next_job()
        assert claimed is not None and claimed["id"] == job_id
        response = client.post(
            f"/api/admin/jobs/{job_id}/cancel", headers=admin_headers()
        )
        assert response.status_code == 409
        assert _job_row(job_id)["status"] == "running"

    def test_cancel_api_cancels_a_queued_job(self, client: TestClient) -> None:
        setup_site(client)
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO media(filename, original_name, mime, size, alt,
                                     owner_id, created_at)
                   VALUES ('2026/05/y.jpg', 'y.jpg', 'image/jpeg', 1, '', 1,
                           '2026-01-01T00:00:00Z')"""
            )
            media_id = int(cursor.lastrowid or 0)
        created = client.post(
            "/api/admin/jobs",
            json={"kind": "prewarm", "media_id": media_id},
            headers=admin_headers(),
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["job"]["id"]
        response = client.post(
            f"/api/admin/jobs/{job_id}/cancel", headers=admin_headers()
        )
        assert response.status_code == 200, response.text
        assert response.json()["job"]["status"] == "cancelled"


class ExecutorTests:
    def test_prewarm_job_executes_the_image_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[int, bool]] = []

        def fake_prewarm(media_id: int, *, force: bool = False) -> bool:
            calls.append((media_id, force))
            return True

        monkeypatch.setattr("app.images.prewarm_media", fake_prewarm)
        job_id = jobs.enqueue_job("prewarm", media_id=42)
        assert jobs.run_once() is True
        assert calls == [(42, False)]
        row = _job_row(job_id)
        assert row["status"] == "done"
        assert row["progress"] == 100
        assert json.loads(row["result"]) == {"media_id": 42, "ready": True}

    def test_failing_handler_marks_the_job_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(media_id: int, *, force: bool = False) -> bool:
            raise RuntimeError("encoder exploded")

        monkeypatch.setattr("app.images.prewarm_media", broken)
        job_id = jobs.enqueue_job("prewarm", media_id=42)
        jobs.run_once()
        row = _job_row(job_id)
        assert row["status"] == "failed"
        assert "encoder exploded" in row["error"]
        assert row["finished_at"]

    def test_export_is_reserved_but_completes(self) -> None:
        job_id = jobs.enqueue_job("export")
        jobs.run_once()
        row = _job_row(job_id)
        assert row["status"] == "done"
        result = json.loads(row["result"])
        assert result["reserved"] is True
        assert "later phase" in result["detail"]

    def test_reencode_without_images_fails_cleanly(self) -> None:
        job_id = jobs.enqueue_job("reencode")
        jobs.run_once()
        row = _job_row(job_id)
        assert row["status"] == "failed"
        assert "没有可重编码的图片" in row["error"]

    def test_run_once_returns_false_when_idle(self) -> None:
        assert jobs.run_once() is False


class WorkerThreadTests:
    def test_worker_thread_consumes_a_job_and_stops(self) -> None:
        worker = jobs.JobWorker(poll_seconds=0.02, heartbeat_seconds=0.05)
        worker.start()
        try:
            assert worker.running is True
            job_id = jobs.enqueue_job("export")
            deadline = time.monotonic() + 5
            row = _job_row(job_id)
            while row["status"] not in {"done", "failed"} and time.monotonic() < deadline:
                time.sleep(0.02)
                row = _job_row(job_id)
            assert row["status"] == "done"
        finally:
            worker.stop()
        assert worker.running is False


class ApiValidationTests:
    def test_job_create_validates_kind_and_media(self, client: TestClient) -> None:
        setup_site(client)
        bad_kind = client.post(
            "/api/admin/jobs", json={"kind": "bogus"}, headers=admin_headers()
        )
        assert bad_kind.status_code == 422
        missing_media = client.post(
            "/api/admin/jobs", json={"kind": "prewarm"}, headers=admin_headers()
        )
        assert missing_media.status_code == 422
        unknown_media = client.post(
            "/api/admin/jobs",
            json={"kind": "prewarm", "media_id": 999},
            headers=admin_headers(),
        )
        assert unknown_media.status_code == 404

    def test_jobs_list_filters_and_limit(self, client: TestClient) -> None:
        setup_site(client)
        for kind in ("gc_derivatives", "export", "rebuild_site"):
            response = client.post(
                "/api/admin/jobs", json={"kind": kind}, headers=admin_headers()
            )
            assert response.status_code == 201, response.text
        listing = client.get(
            "/api/admin/jobs",
            params={"kind": "export", "limit": 5},
            headers=admin_headers(),
        )
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert listing.json()["items"][0]["kind"] == "export"

    def test_jobs_require_authentication(self, client: TestClient) -> None:
        setup_site(client)
        client.post("/api/auth/logout")
        assert client.get("/api/admin/jobs").status_code == 401

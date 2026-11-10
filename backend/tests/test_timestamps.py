"""UTC formatting and publish-time validation regressions."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.content import normalize_iso_datetime
from app.errors import ApiError
from app.security import iso_utc
from app.services.content_admin import normalize_schedule
from tests.conftest import setup_site


def test_utc_seconds_and_offset_rollover():
    value = datetime(2027, 1, 1, 4, 30, 45, 900000, tzinfo=timezone(timedelta(hours=8)))
    assert iso_utc(value) == "2026-12-31T20:30:45Z"
    assert normalize_iso_datetime(value.isoformat()) == iso_utc(value)
    assert iso_utc(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00Z"


def test_invalid_publish_time_cannot_publish_immediately():
    with pytest.raises(ApiError):
        normalize_schedule("scheduled", "invalid")


def test_session_expiry_uses_the_same_precision(client):
    from app.db import db

    setup_site(client)
    with db() as conn:
        expiry = conn.execute("SELECT expires_at FROM sessions LIMIT 1").fetchone()[0]
    assert len(expiry) == 20
    assert expiry.endswith("Z")


def test_import_normalizes_offsets_and_rejects_invalid_times(client):
    from app.services.backup import validate_document

    setup_site(client)
    document = client.get("/api/admin/export").json()
    document["users"][0]["created_at"] = "2027-01-01T04:30:45.900+08:00"
    rows = validate_document(document)
    assert rows["users"][0]["created_at"] == "2026-12-31T20:30:45Z"
    document["users"][0]["created_at"] = "invalid"
    with pytest.raises(ApiError):
        validate_document(document)

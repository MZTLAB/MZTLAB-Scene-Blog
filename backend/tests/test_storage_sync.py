"""Force-sync of local media/cache files to object storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.storage import LocalStorage
from app.storage_sync import local_objects, sync_local_to_remote


def local_storage(root: Path) -> LocalStorage:
    storage = LocalStorage()
    storage.upload_dir = root / "uploads"
    storage.cache_dir = root / "cache"
    storage.upload_dir.mkdir(parents=True, exist_ok=True)
    storage.cache_dir.mkdir(parents=True, exist_ok=True)
    return storage


class StorageSyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.local = local_storage(root / "local")
        # A local backend is a perfect stand-in for a remote during tests: the
        # sync only relies on the Storage interface (exists/size/save/read).
        self.remote = local_storage(root / "remote")
        self.local.save("2026/05/a.jpg", b"original-a", "image/jpeg")
        self.local.save("2026/05/b.mp3", b"audio-b", "audio/mpeg")
        self.local.save("_derived/1/token/tile/720.avif", b"derived-a", "image/avif")
        self.local.save("_derived/1/token/hero/1600.avif", b"derived-b", "image/avif")

    def tearDown(self):
        self._tmp.cleanup()

    def test_force_uploads_every_local_object(self):
        result = sync_local_to_remote(self.local, self.remote, force=True)
        self.assertEqual(result.total, 4)
        self.assertEqual(result.uploaded, 4)
        self.assertEqual(result.failed, 0)
        self.assertTrue(self.remote.exists("2026/05/a.jpg"))
        self.assertTrue(self.remote.exists("_derived/1/token/tile/720.avif"))
        self.assertEqual(self.remote.read("_derived/1/token/tile/720.avif"), b"derived-a")

    def test_non_force_skips_identical_and_refreshes_different_files(self):
        # Identical copy on both sides → skipped.
        self.remote.save("2026/05/a.jpg", b"original-a", "image/jpeg")
        # Same key, different content/size → re-uploaded.
        self.remote.save("2026/05/b.mp3", b"old", "audio/mpeg")
        result = sync_local_to_remote(self.local, self.remote, force=False)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.uploaded, 3)
        self.assertEqual(self.remote.read("2026/05/b.mp3"), b"audio-b")

    def test_scope_limits_what_is_synced(self):
        result = sync_local_to_remote(self.local, self.remote, force=True, scope="derivatives")
        self.assertEqual(result.total, 2)
        self.assertTrue(self.remote.exists("_derived/1/token/tile/720.avif"))
        self.assertFalse(self.remote.exists("2026/05/a.jpg"))

        self.remote.delete_prefix("_derived")
        result = sync_local_to_remote(self.local, self.remote, force=True, scope="originals")
        self.assertEqual(result.total, 2)
        self.assertTrue(self.remote.exists("2026/05/a.jpg"))
        self.assertFalse(self.remote.exists("_derived/1/token/tile/720.avif"))

    def test_local_objects_reports_sizes(self):
        objects = dict(local_objects(self.local, "all"))
        self.assertEqual(objects["2026/05/a.jpg"], len(b"original-a"))
        self.assertIn("_derived/1/token/hero/1600.avif", objects)

    def test_unknown_scope_raises(self):
        with self.assertRaises(ValueError):
            sync_local_to_remote(self.local, self.remote, scope="everything")


if __name__ == "__main__":
    unittest.main()

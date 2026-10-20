"""Storage abstraction: local backend safety and key handling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.storage import (
    LocalStorage,
    MirrorStorage,
    StorageError,
    StorageMissing,
    content_type_for,
)


def local_storage(root: Path) -> LocalStorage:
    storage = LocalStorage()
    storage.upload_dir = root / "uploads"
    storage.cache_dir = root / "cache"
    storage.upload_dir.mkdir(parents=True, exist_ok=True)
    storage.cache_dir.mkdir(parents=True, exist_ok=True)
    return storage


class LocalStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.storage = LocalStorage()
        self.storage.upload_dir = root / "uploads"
        self.storage.cache_dir = root / "cache"
        self.storage.upload_dir.mkdir()
        self.storage.cache_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_originals_and_derivatives_use_different_roots(self):
        self.storage.save("2026/05/a.jpg", b"original", "image/jpeg")
        self.storage.save("_derived/1/token/tile/720.avif", b"derived", "image/avif")
        self.assertEqual(
            self.storage.local_path("2026/05/a.jpg"),
            self.storage.upload_dir / "2026/05/a.jpg",
        )
        self.assertEqual(
            self.storage.local_path("_derived/1/token/tile/720.avif"),
            self.storage.cache_dir / "_derived/1/token/tile/720.avif",
        )
        self.assertEqual(self.storage.read("2026/05/a.jpg"), b"original")
        self.assertTrue(self.storage.exists("_derived/1/token/tile/720.avif"))

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(StorageError):
            self.storage.local_path("../outside.jpg")
        with self.assertRaises(StorageError):
            self.storage.save("../../etc/passwd", b"x", "text/plain")

    def test_missing_read_raises_storage_missing(self):
        with self.assertRaises(StorageMissing):
            self.storage.read("2026/05/none.jpg")
        self.assertFalse(self.storage.exists("2026/05/none.jpg"))

    def test_delete_and_prefix_cleanup(self):
        self.storage.save("_derived/9/t/tile/720.avif", b"a", "image/avif")
        self.storage.save("_derived/9/t/tile/2560.avif", b"b", "image/avif")
        self.storage.save("_derived/10/t/tile/720.avif", b"c", "image/avif")
        removed = self.storage.delete_prefix("_derived/9")
        self.assertEqual(removed, 2)
        self.assertFalse(self.storage.exists("_derived/9/t/tile/720.avif"))
        self.assertTrue(self.storage.exists("_derived/10/t/tile/720.avif"))

    def test_local_backend_never_exposes_direct_urls(self):
        self.assertIsNone(self.storage.public_url("_derived/1/x/tile/720.avif"))
        self.assertIsNone(self.storage.derived_base(1, "token"))


class ContentTypeTests(unittest.TestCase):
    def test_known_derivative_types(self):
        self.assertEqual(content_type_for("a/b/720.avif"), "image/avif")
        self.assertEqual(content_type_for("a/b/720.webp"), "image/webp")
        self.assertEqual(content_type_for("a/b/720.jpg"), "image/jpeg")
        self.assertEqual(content_type_for("2026/05/song.mp3"), "audio/mpeg")
        self.assertEqual(content_type_for("weird.bin"), "application/octet-stream")


class MirrorStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.primary = local_storage(root / "primary")
        self.backup = local_storage(root / "backup")
        self.mirror = MirrorStorage(self.primary, self.backup)
        self.key = "2026/05/photo.jpg"

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_writes_primary_and_backup(self):
        self.mirror.save(self.key, b"hello", "image/jpeg")
        self.assertEqual(self.primary.read(self.key), b"hello")
        self.assertEqual(self.backup.read(self.key), b"hello")

    def test_read_prefers_primary_but_falls_back_to_backup(self):
        self.mirror.save(self.key, b"hello", "image/jpeg")
        self.primary.delete(self.key)
        self.assertEqual(self.mirror.read(self.key), b"hello")
        self.assertTrue(self.mirror.exists(self.key))

    def test_delete_removes_both_copies(self):
        self.mirror.save(self.key, b"hello", "image/jpeg")
        self.mirror.delete(self.key)
        self.assertFalse(self.primary.exists(self.key))
        self.assertFalse(self.backup.exists(self.key))

    def test_backup_failure_does_not_fail_the_write(self):
        def broken_save(*args, **kwargs):
            raise StorageError("disk full")

        self.backup.save = broken_save  # type: ignore[method-assign]
        self.mirror.save(self.key, b"hello", "image/jpeg")
        self.assertEqual(self.primary.read(self.key), b"hello")

    def test_derivatives_are_mirrored_too(self):
        key = "_derived/7/token/tile/720.avif"
        self.mirror.save(key, b"avif", "image/avif")
        self.assertTrue(self.primary.exists(key))
        self.assertTrue(self.backup.exists(key))
        self.assertIsNotNone(self.mirror.backup_path(key))


if __name__ == "__main__":
    unittest.main()

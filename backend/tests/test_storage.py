"""Storage abstraction: local backend safety, key handling, typed config."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import storage
from app.settings import Settings
from app.storage import (
    LocalStorage,
    MirrorStorage,
    StorageError,
    StorageMissing,
    content_type_for,
    storage_config,
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

    def test_iter_keys_scopes_and_filters_temp_files(self):
        self.storage.save("2026/05/a.jpg", b"a", "image/jpeg")
        self.storage.save("_derived/1/token/tile/720.avif", b"b", "image/avif")
        self.storage.save("2026/05/.hidden", b"x", "text/plain")
        self.storage.save("2026/05/b.jpg.tmp", b"x", "text/plain")
        originals = list(self.storage.iter_keys("originals"))
        derivatives = list(self.storage.iter_keys("derivatives"))
        self.assertEqual(originals, ["2026/05/a.jpg"])
        self.assertEqual(derivatives, ["_derived/1/token/tile/720.avif"])
        self.assertEqual(
            set(self.storage.iter_keys("all")),
            {"2026/05/a.jpg", "_derived/1/token/tile/720.avif"},
        )

    def test_local_backend_never_exposes_direct_urls(self):
        self.assertIsNone(self.storage.public_url("_derived/1/x/tile/720.avif"))
        self.assertIsNone(self.storage.derived_base(1, "token"))


class _FakeS3Primary:
    """Minimal primary backend used to test MirrorStorage delegation."""

    def __init__(self):
        self.client = object()
        self.config = object()

    def health(self):
        return {"ok": True, "backend": "s3", "bucket": "bucket"}


class MirrorHealthTests(unittest.TestCase):
    def test_health_and_client_delegate_to_the_primary(self):
        primary = _FakeS3Primary()
        storage = LocalStorage()
        storage.upload_dir = Path(tempfile.mkdtemp())
        storage.cache_dir = Path(tempfile.mkdtemp())
        try:
            mirror = MirrorStorage(primary, storage)
            health = mirror.health()
            self.assertTrue(health["ok"])
            self.assertEqual(health["backend"], "s3")
            self.assertTrue(health["backup_ok"])
            self.assertIs(mirror.client, primary.client)
            self.assertIs(mirror.config, primary.config)
        finally:
            for directory in (storage.upload_dir, storage.cache_dir):
                for child in sorted(directory.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                    else:
                        child.rmdir()
                directory.rmdir()

    def test_local_health_reports_ok(self):
        with tempfile.TemporaryDirectory() as root:
            storage = local_storage(Path(root))
            self.assertTrue(storage.health()["ok"])


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


class StorageConfigTests(unittest.TestCase):
    """The typed settings API + environment-only credentials."""

    def _settings(self, **overrides: object) -> Settings:
        settings = Settings()
        for key, value in overrides.items():
            setattr(settings.advanced.storage, key, value)
        return settings

    def _config(
        self,
        settings: Settings | None = None,
        *,
        env: dict[str, str] | None = None,
        backend_env: str = "",
        public_base_url_env: str = "",
        path_style_env: bool = False,
        load_error: Exception | None = None,
    ) -> storage.StorageConfig:
        credentials = env or {
            "storage_s3_access_key": "",
            "storage_s3_secret_key": "",
        }
        patcher = mock.patch.object(storage, "load_settings_cached")
        load = patcher.start()
        if load_error is not None:
            load.side_effect = load_error
        else:
            load.return_value = settings or Settings()
        patches = [
            mock.patch.object(storage, "S3_ENV", credentials),
            mock.patch.object(storage, "S3_BACKEND_ENV", backend_env),
            mock.patch.object(storage, "S3_PUBLIC_BASE_URL_ENV", public_base_url_env),
            mock.patch.object(storage, "S3_PATH_STYLE_ENV", path_style_env),
        ]
        for extra in patches:
            extra.start()
        self.addCleanup(patcher.stop)
        for extra in patches:
            self.addCleanup(extra.stop)
        return storage_config()

    def test_defaults_to_local_without_credentials(self) -> None:
        config = self._config()
        self.assertEqual(config.backend, "local")
        self.assertEqual(config.serve_mode, "auto")
        self.assertEqual(config.access_key, "")
        self.assertEqual(config.secret_key, "")
        self.assertEqual(config.region, "auto")
        self.assertEqual(config.prefix, "mztlab")
        self.assertFalse(config.describe()["secret_configured"])

    def test_settings_supply_coordinates_but_never_credentials(self) -> None:
        config = self._config(
            self._settings(
                backend="s3",
                serve_mode="direct",
                public_base_url="https://cdn.example.com/",
                s3_endpoint="https://r2.example.com/",
                s3_bucket="bucket",
                s3_region="auto",
                s3_prefix="site",
                s3_path_style=True,
                backup_local=True,
            )
        )
        self.assertEqual(config.backend, "s3")
        self.assertEqual(config.serve_mode, "direct")
        self.assertEqual(config.public_base_url, "https://cdn.example.com")
        self.assertEqual(config.endpoint, "https://r2.example.com")
        self.assertEqual(config.bucket, "bucket")
        self.assertEqual(config.prefix, "site")
        self.assertTrue(config.path_style)
        self.assertTrue(config.backup_local)
        self.assertTrue(config.direct_enabled)
        # Secrets have no representation in the typed settings document.
        self.assertEqual(config.access_key, "")
        self.assertEqual(config.secret_key, "")
        self.assertNotIn("access_key", config.describe())
        self.assertNotIn("secret_key", config.describe())

    def test_credentials_come_from_the_environment(self) -> None:
        config = self._config(
            env={
                "storage_s3_access_key": "AK",
                "storage_s3_secret_key": "SK",
            }
        )
        self.assertEqual(config.access_key, "AK")
        self.assertEqual(config.secret_key, "SK")
        self.assertTrue(config.describe()["secret_configured"])

    def test_environment_overrides_the_stored_values(self) -> None:
        config = self._config(
            self._settings(backend="local", public_base_url="https://stored.example"),
            backend_env="s3",
            public_base_url_env="https://env.example",
            path_style_env=True,
        )
        self.assertEqual(config.backend, "s3")
        self.assertEqual(config.public_base_url, "https://env.example")
        self.assertTrue(config.path_style)

    def test_unreachable_settings_fall_back_to_defaults(self) -> None:
        config = self._config(load_error=RuntimeError("database not ready"))
        self.assertEqual(config.backend, "local")
        self.assertEqual(config.bucket, "")


if __name__ == "__main__":
    unittest.main()

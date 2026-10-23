"""Storage abstraction: local backend, narrow read interface, typed config.

3.0.0 removed `local_path()` from the Storage contract (P-J1): readers use
`size()` + `stream()` only, and `derived_public_prefix()` replaced the old
`derived_base()` helper.
"""

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
    StorageConfig,
    StorageError,
    StorageMissing,
    content_type_for,
    storage_config,
)


def local_storage(root: Path) -> LocalStorage:
    instance = LocalStorage()
    instance.upload_dir = root / "uploads"
    instance.cache_dir = root / "cache"
    instance.upload_dir.mkdir(parents=True, exist_ok=True)
    instance.cache_dir.mkdir(parents=True, exist_ok=True)
    return instance


def _temp_upload(directory: Path, payload: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as handle:
        handle.write(payload)
    return Path(handle.name)


class LocalStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = local_storage(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_originals_and_derivatives_use_different_roots(self):
        self.storage.save("2026/05/a.jpg", b"original", "image/jpeg")
        self.storage.save("_derived/1/token/tile/720.avif", b"derived", "image/avif")
        self.assertEqual(self.storage.read("2026/05/a.jpg"), b"original")
        self.assertTrue(self.storage.exists("_derived/1/token/tile/720.avif"))
        self.assertTrue((self.root / "uploads/2026/05/a.jpg").is_file())
        self.assertTrue((self.root / "cache/_derived/1/token/tile/720.avif").is_file())

    def test_stream_yields_the_relevant_bytes(self):
        self.storage.save("2026/05/a.jpg", b"hello world", "image/jpeg")
        self.assertEqual(b"".join(self.storage.stream("2026/05/a.jpg")), b"hello world")

    def test_stream_missing_key_raises_storage_missing(self):
        with self.assertRaises(StorageMissing):
            self.storage.stream("2026/05/none.jpg")

    def test_path_traversal_is_rejected(self):
        # Keys are rejected regardless of the host OS path semantics: a single
        # backslash is a separator on Windows but a filename character on POSIX.
        for key in (
            "../../etc/passwd",
            "..\\windows.txt",
            "../outside.jpg",
            "/etc/passwd",
            "C:\\windows\\win.ini",
            "2026/05/../../../etc/passwd",
            "a\x00b",
        ):
            with self.assertRaises(StorageError):
                self.storage.save(key, b"x", "text/plain")
            with self.assertRaises(StorageError):
                self.storage.size(key)
        with self.assertRaises(StorageError):
            self.storage.delete_prefix("../outside")

    def test_missing_read_raises_storage_missing(self):
        with self.assertRaises(StorageMissing):
            self.storage.read("2026/05/none.jpg")
        self.assertFalse(self.storage.exists("2026/05/none.jpg"))

    def test_size_reports_the_stored_length(self):
        self.storage.save("2026/05/a.jpg", b"1234567", "image/jpeg")
        self.assertEqual(self.storage.size("2026/05/a.jpg"), 7)

    def test_save_file_moves_the_temporary_upload_atomically(self):
        source = _temp_upload(self.storage.upload_dir, b"streamed")
        self.storage.save_file("2026/05/moved.jpg", source, "image/jpeg")
        self.assertFalse(source.exists())
        self.assertEqual(self.storage.read("2026/05/moved.jpg"), b"streamed")

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
        self.assertIsNone(self.storage.derived_public_prefix(1))

    def test_local_health_reports_ok(self):
        self.assertTrue(self.storage.health()["ok"])


class _FakeS3Primary:
    """Minimal primary backend used to test MirrorStorage delegation."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.client = object()
        self.config = object()
        self.objects = dict(objects or {})

    def health(self):
        return {"ok": True, "backend": "s3", "bucket": "bucket"}

    def stream(self, key):
        if key not in self.objects:
            raise StorageMissing(key)
        return iter([self.objects[key]])

    def public_url(self, key):
        return f"https://cdn.example.com/{key}"

    def derived_public_prefix(self, media_id):
        return f"https://cdn.example.com/_derived/{media_id}"


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

    def test_save_file_writes_primary_and_backup(self):
        source = _temp_upload(self.primary.upload_dir, b"hello")
        self.mirror.save_file(self.key, source, "image/jpeg")
        self.assertEqual(self.primary.read(self.key), b"hello")
        self.assertEqual(self.backup.read(self.key), b"hello")

    def test_read_prefers_primary_but_falls_back_to_backup(self):
        self.mirror.save(self.key, b"hello", "image/jpeg")
        self.primary.delete(self.key)
        self.assertEqual(self.mirror.read(self.key), b"hello")
        self.assertTrue(self.mirror.exists(self.key))

    def test_stream_falls_back_to_the_local_backup(self):
        self.mirror.save(self.key, b"hello", "image/jpeg")
        self.primary.delete(self.key)
        self.assertEqual(b"".join(self.mirror.stream(self.key)), b"hello")

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


class S3DerivedPrefixTests(unittest.TestCase):
    def _config(self, **overrides: object) -> StorageConfig:
        values = dict(
            backend="s3",
            serve_mode="direct",
            public_base_url="https://cdn.example.com",
            endpoint="https://r2.example.com",
            bucket="bucket",
            region="auto",
            access_key="",
            secret_key="",
            prefix="mztlab",
            path_style=False,
            backup_local=False,
        )
        values.update(overrides)
        return StorageConfig(**values)  # type: ignore[arg-type]

    def test_direct_mode_yields_the_derivative_prefix(self):
        backend = storage.S3Storage(self._config())
        self.assertEqual(
            backend.derived_public_prefix(42),
            "https://cdn.example.com/mztlab/_derived/42",
        )

    def test_proxy_mode_has_no_direct_prefix(self):
        backend = storage.S3Storage(self._config(serve_mode="proxy"))
        self.assertIsNone(backend.derived_public_prefix(42))
        backend = storage.S3Storage(self._config(public_base_url=""))
        self.assertIsNone(backend.derived_public_prefix(42))


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

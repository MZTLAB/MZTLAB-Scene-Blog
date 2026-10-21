"""Password hashing, password policy, sessions and small in-process rate limiters."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Deque, Protocol

from .config import SESSION_DAYS

logger = logging.getLogger("mztlab.security")

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1

# Password policy. The audit report found that `admin123` / `user1234` were
# accepted because only a length check existed. We now require length,
# character variety and reject the usual suspects.
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
PASSWORD_CLASSES = (
    re.compile(r"[a-z]"),
    re.compile(r"[A-Z]"),
    re.compile(r"[0-9]"),
    re.compile(r"[^A-Za-z0-9]"),
)

# Lower-case entries. Trailing digits are stripped before the lookup so that
# `admin1234` is rejected as well; the list therefore holds the stems too.
COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "87654321",
        "password",
        "passw0rd",
        "p@ssword",
        "qwerty",
        "qwertyuiop",
        "abc123",
        "abcdefgh",
        "letmein",
        "welcome",
        "iloveyou",
        "dragon",
        "monkey",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "master",
        "shadow",
        "superman",
        "batman",
        "trustno1",
        "admin",
        "administrator",
        "root",
        "toor",
        "test",
        "test123",
        "guest",
        "user",
        "user123",
        "mztlab",
        "scene",
        "changeme",
        "default",
        "secret",
    }
)


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=64,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, digest_b64 = encoded.split("$")
        if algorithm != "scrypt":
            return False
        expected = _unb64(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def password_policy_error(password: str, username: str | None = None) -> str | None:
    """Return a human-readable policy violation, or None when acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"密码至少 {MIN_PASSWORD_LENGTH} 位"
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"密码不能超过 {MAX_PASSWORD_LENGTH} 位"
    lowered = password.lower()
    stem = re.sub(r"\d+$", "", lowered)
    if lowered in COMMON_PASSWORDS or stem in COMMON_PASSWORDS:
        return "密码过于常见，请使用更独特的口令"
    if username and len(username.strip()) >= 3 and username.strip().lower() in lowered:
        return "密码不能包含用户名"
    variety = sum(1 for pattern in PASSWORD_CLASSES if pattern.search(password))
    if variety < 3:
        return "密码需包含小写字母、大写字母、数字、符号中的至少三类"
    if len(set(password)) < 5:
        return "密码中重复字符过多"
    return None


def new_session_token() -> str:
    return secrets.token_urlsafe(40)


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)


def iso_utc(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RateLimitStore(Protocol):
    """Backing store for rate-limit buckets.

    The 3.0.0 default is process-local memory. The protocol exists so a future
    multi-worker deployment can swap in a shared store without touching the
    routes, and so the single-worker requirement is explicit.
    """

    def bucket(self, key: str) -> Deque[float]: ...

    def drop(self, key: str) -> None: ...

    def keys(self) -> list[str]: ...


class MemoryRateLimitStore:
    """In-process sliding-window buckets guarded by a lock."""

    def __init__(self) -> None:
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def bucket(self, key: str) -> Deque[float]:
        with self._lock:
            return self._hits[key]

    def drop(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._hits)


RATE_LIMIT_STORE: RateLimitStore = MemoryRateLimitStore()


class RateLimiter:
    """Sliding-window limiter over a `RateLimitStore`.

    `allow()` is the atomic check-and-consume used by login attempts and
    uploads; `reset()` lets a success clear the bucket (so failures are counted
    until the first success, then forgotten). There is deliberately no
    `sleep`-based delay: a failed login returns 429 + `Retry-After` immediately
    and never occupies a request thread.
    """

    def __init__(
        self, limit: int, window_seconds: int, store: RateLimitStore | None = None
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self.store = store or RATE_LIMIT_STORE

    def _prune(self, bucket: Deque[float], now: float) -> None:
        cutoff = now - self.window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _cleanup(self, now: float) -> None:
        if len(self.store.keys()) <= 4096:
            return
        cutoff = now - self.window
        for name in self.store.keys():
            bucket = self.store.bucket(name)
            if not bucket or bucket[-1] <= cutoff:
                self.store.drop(name)

    def count(self, key: str) -> int:
        now = time.monotonic()
        bucket = self.store.bucket(key)
        self._prune(bucket, now)
        return len(bucket)

    def is_blocked(self, key: str) -> bool:
        return self.count(key) >= self.limit

    def record(self, key: str) -> int:
        now = time.monotonic()
        bucket = self.store.bucket(key)
        self._prune(bucket, now)
        bucket.append(now)
        self._cleanup(now)
        return len(bucket)

    def reset(self, key: str) -> None:
        self.store.drop(key)

    def allow(self, key: str) -> bool:
        """Check and consume one slot atomically.

        This is the only correct primitive for per-attempt limits: a separate
        `is_blocked()` + `record()` pair lets concurrent requests pass between
        the two calls.
        """
        now = time.monotonic()
        bucket = self.store.bucket(key)
        self._prune(bucket, now)
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        self._cleanup(now)
        return True

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest hit leaves the window (minimum 1)."""
        now = time.monotonic()
        bucket = self.store.bucket(key)
        self._prune(bucket, now)
        if not bucket:
            return 1
        return max(1, int(self.window - (now - bucket[0])) + 1)


# Login limits stay in the application (the ingress is operator-maintained and
# cannot be relied on for security): per-IP and per-IP+account attempt limits,
# plus a high-ceiling per-account throttle so one source cannot cheaply lock a
# real administrator out.
login_ip_limiter = RateLimiter(limit=30, window_seconds=300)
login_pair_limiter = RateLimiter(limit=6, window_seconds=300)
login_account_limiter = RateLimiter(limit=60, window_seconds=900)

# Editor previews are debounced client-side, but a misbehaving client (or a
# held-down key in split view) could still hammer the Markdown renderer.
preview_limiter = RateLimiter(limit=60, window_seconds=60)


def clear_login_failures(ip: str, username: str) -> None:
    login_pair_limiter.reset(f"{ip}|{username}")
    login_account_limiter.reset(username)
    login_ip_limiter.reset(ip)

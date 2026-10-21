#!/usr/bin/env python3
"""One-command MZTLAB 3.0.0 acceptance run.

Runs every gate the release checklist needs, prints a PASS/FAIL table and exits
non-zero when any executed step fails. Standard library only; works on Windows
and Linux and auto-detects the backend virtualenv.

    python scripts/verify.py                  # full run (includes runtime smoke)
    python scripts/verify.py --skip-slow      # quick loop: no mypy/pytest/build
    python scripts/verify.py --no-smoke       # everything except the runtime smoke
    python scripts/verify.py --only backend-pytest,contract-audit
    python scripts/verify.py --list

Steps (see docs/REFACTOR-3.0.0.md section 6.2):

    backend-ruff     ruff check app tests
    backend-mypy     mypy app
    backend-pytest   pytest tests
    contract-audit   python -m app.scripts.audit_contracts
    contract-export  regenerate openapi.json and detect drift
    contract-types   npm run gen:types and detect TypeScript type drift
    render-audit     python -m app.scripts.check_public_render (SSG reserve R3)
    docs-drift       regenerate docs/SCHEMA.md + docs/API.md and detect drift
    frontend-check   npm run check
    frontend-lint    npm run lint (warnings are informational, not failures)
    frontend-build   npm run build
    smoke            boot uvicorn on a temp data dir and assert the public API

Drift steps snapshot the generated files, regenerate them, compare bytes and
restore the snapshot, so running this script never leaves the worktree dirty.
The smoke step refuses to run when `.env` files pin BLOG_DATA_DIR/BLOG_DB_PATH
(it must never touch a developer's real database).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OPENAPI = FRONTEND / "src" / "api" / "openapi.json"
GENERATED_TYPES = FRONTEND / "src" / "api" / "types.gen.ts"
SCHEMA_DOC = ROOT / "docs" / "SCHEMA.md"
API_DOC = ROOT / "docs" / "API.md"

GIT = shutil.which("git")
NPM = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
# `npm` is a .cmd shim on Windows; cmd.exe is the portable way to execute it.
NPM_PREFIX: list[str] = ["cmd", "/c"] if os.name == "nt" else []

# Step -> slow (skipped by --skip-slow).
STEPS: dict[str, bool] = {
    "backend-ruff": False,
    "backend-mypy": True,
    "backend-pytest": True,
    "contract-audit": False,
    "contract-export": False,
    "contract-types": False,
    "render-audit": False,
    "docs-drift": False,
    "frontend-check": False,
    "frontend-lint": False,
    "frontend-build": True,
    "smoke": False,
}

LINT_SUMMARY = re.compile(r"(\d+)\s+problems?\s*\((\d+)\s+errors?,\s*(\d+)\s+warnings?\)")
DEFAULT_TIMEOUT = 1800


@dataclass
class Result:
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""
    seconds: float = 0.0
    output: str = ""
    command: str = ""


def backend_python() -> Path:
    """The backend venv interpreter, falling back to the current interpreter."""
    candidates = [
        BACKEND / ".venv" / "Scripts" / "python.exe",
        BACKEND / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


PYTHON = backend_python()


def _command_text(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def _run(
    name: str,
    command: list[str],
    cwd: Path,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> Result:
    """Run one external command; a non-zero exit is a failed step."""
    command = [str(part) for part in command]
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return Result(
            name,
            "FAIL",
            f"command not found: {command[0]}",
            time.monotonic() - started,
            command=_command_text(command),
        )
    except subprocess.TimeoutExpired:
        return Result(
            name,
            "FAIL",
            f"timed out after {timeout}s",
            time.monotonic() - started,
            command=_command_text(command),
        )
    except OSError as error:  # e.g. a broken venv interpreter
        return Result(
            name,
            "FAIL",
            f"could not start {command[0]}: {error}",
            time.monotonic() - started,
            command=_command_text(command),
        )
    output = process.stdout or ""
    if process.stderr:
        output = f"{output}\n{process.stderr}" if output else process.stderr
    seconds = time.monotonic() - started
    if process.returncode == 0:
        return Result(name, "PASS", "", seconds, output, _command_text(command))
    return Result(
        name,
        "FAIL",
        f"exit code {process.returncode}",
        seconds,
        output,
        _command_text(command),
    )


def _npm(name: str, *args: str, timeout: int = DEFAULT_TIMEOUT) -> Result:
    return _run(
        name,
        [*NPM_PREFIX, NPM, "run", *args],
        FRONTEND,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Generated-artifact drift checks
# ---------------------------------------------------------------------------

def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.is_file() else None for path in paths}


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, data in snapshot.items():
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)


def _git_diff_stat(paths: list[Path]) -> str:
    if not GIT:
        return ""
    relative = [path.relative_to(ROOT).as_posix() for path in paths]
    process = subprocess.run(
        [GIT, "diff", "--stat", "--", *relative],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return (process.stdout or "").strip()


def _drift_check(
    name: str,
    generate: Callable[[], Result],
    paths: list[Path],
) -> Result:
    """Regenerate artifacts, compare to the checked-in files, restore them."""
    before = _snapshot(paths)
    try:
        generation = generate()
        if generation.status != "PASS":
            generation.name = name
            generation.detail = f"generator failed: {generation.detail}"
            return generation
        after = _snapshot(paths)
        changed = [
            path.relative_to(ROOT).as_posix()
            for path in paths
            if before.get(path) != after.get(path)
        ]
        if not changed:
            return Result(name, "PASS", f"{len(paths)} artifact(s) identical", generation.seconds)
        stat = _git_diff_stat(paths)
        detail = (
            "generated output differs from the checked-in artifacts: "
            + ", ".join(changed)
            + " - run the generator and commit the result"
        )
        if stat:
            detail += "\n" + stat
        return Result(name, "FAIL", detail, generation.seconds, generation.output)
    finally:
        _restore(before)


# ---------------------------------------------------------------------------
# Runtime smoke
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers_out = {key.lower(): value for key, value in response.headers.items()}
            return response.status, headers_out, response.read()
    except urllib.error.HTTPError as error:
        headers_out = {key.lower(): value for key, value in error.headers.items()}
        return error.code, headers_out, error.read()


def _conflicting_env_files() -> list[str]:
    """`.env` files that pin the database location the smoke test must isolate."""
    conflicts: list[str] = []
    for path in (ROOT / ".env", BACKEND / ".env"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in {"BLOG_DATA_DIR", "BLOG_DB_PATH"}:
                conflicts.append(f"{path.name}:{key}")
    return conflicts


def _remove_tree(path: Path) -> None:
    """Remove a temp tree; retry briefly because Windows may still hold handles."""
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 4:
                return
            time.sleep(0.3 * (attempt + 1))


def _smoke() -> Result:
    """Boot the real app on a temporary data dir and probe the public API."""
    started = time.monotonic()
    conflicts = _conflicting_env_files()
    if conflicts:
        return Result(
            "smoke",
            "SKIP",
            "refusing to run: .env pins the database location ("
            + ", ".join(conflicts)
            + "); run with a sanitized environment or --no-smoke",
        )
    temp_dir = Path(tempfile.mkdtemp(prefix="mztlab-smoke-"))
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    log_path = temp_dir / "server.log"
    env = {key: value for key, value in os.environ.items() if not key.startswith("BLOG_")}
    env.update(
        {
            "BLOG_DATA_DIR": str(temp_dir),
            "BLOG_SEED_DEMO": "true",
            "BLOG_ADMIN_USER": "smoke-admin",
            "BLOG_ADMIN_PASSWORD": "Sm0ke-Test-Passphrase!",
            "BLOG_ADMIN_NAME": "Smoke",
            "BLOG_DISABLE_JOBS_WORKER": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    command = [
        str(PYTHON),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    checks: list[tuple[str, bool, str]] = []
    process: subprocess.Popen[bytes] | None = None
    try:
        with log_path.open("wb") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=str(BACKEND),
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            ready = False
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    status, _, _ = _http_get(f"{base}/api/health", timeout=2)
                    if status == 200:
                        ready = True
                        break
                except (urllib.error.URLError, OSError, TimeoutError):
                    pass
                time.sleep(0.3)
            if ready:
                checks.extend(_smoke_checks(base))
            else:
                checks.append(
                    ("server ready", False, "/api/health did not answer within 90s")
                )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log = ""
        with contextlib.suppress(OSError):
            log = log_path.read_text(encoding="utf-8", errors="replace")
        _remove_tree(temp_dir)

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = [(name, message) for name, ok, message in checks if not ok]
    detail = f"{passed}/{len(checks)} checks passed"
    if failed:
        detail += "; " + "; ".join(f"{name}: {message}" for name, message in failed)
    status = "PASS" if not failed else "FAIL"
    seconds = time.monotonic() - started
    return Result("smoke", status, detail, seconds, log, _command_text(command))


def _smoke_checks(base: str) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    status, _, body = _http_get(f"{base}/api/site")
    grouped = False
    if status == 200:
        try:
            settings = json.loads(body).get("settings") or {}
            grouped = isinstance(settings, dict) and {
                "site",
                "appearance",
                "copy",
            } <= set(settings) and "advanced" not in settings
        except json.JSONDecodeError:
            grouped = False
    checks.append(
        (
            "/api/site grouped settings",
            status == 200 and grouped,
            f"status={status}, grouped={grouped}",
        )
    )

    status, headers, body = _http_get(f"{base}/api/bootstrap?route=home")
    etag = headers.get("etag", "")
    page_kind = ""
    if status == 200:
        try:
            page_kind = str((json.loads(body).get("page") or {}).get("kind") or "")
        except json.JSONDecodeError:
            page_kind = ""
    checks.append(
        (
            "/api/bootstrap?route=home",
            status == 200 and bool(etag) and page_kind == "home",
            f"status={status}, etag={etag or '(missing)'}, kind={page_kind or '(missing)'}",
        )
    )

    status, _, body = _http_get(f"{base}/api/posts")
    post_count = -1
    if status == 200:
        try:
            post_count = len(json.loads(body).get("items") or [])
        except json.JSONDecodeError:
            post_count = -1
    checks.append(
        (
            "/api/posts",
            status == 200 and post_count >= 0,
            f"status={status}, items={post_count}",
        )
    )

    if etag:
        status, _, _ = _http_get(
            f"{base}/api/bootstrap?route=home",
            headers={"If-None-Match": etag},
        )
    else:
        status = 0
    checks.append(("If-None-Match -> 304", status == 304, f"status={status}"))

    status, _, _ = _http_get(f"{base}/api/comments")
    checks.append(("/api/comments -> 404", status == 404, f"status={status}"))
    return checks


# ---------------------------------------------------------------------------
# Step builders
# ---------------------------------------------------------------------------

def _step_backend_ruff() -> Result:
    return _run(
        "backend-ruff",
        [str(PYTHON), "-m", "ruff", "check", "app", "tests"],
        BACKEND,
        timeout=300,
    )


def _step_backend_mypy() -> Result:
    return _run("backend-mypy", [str(PYTHON), "-m", "mypy", "app"], BACKEND, timeout=900)


def _step_backend_pytest() -> Result:
    return _run(
        "backend-pytest",
        [str(PYTHON), "-m", "pytest", "tests", "-q", "-p", "no:warnings"],
        BACKEND,
        timeout=1800,
    )


def _step_contract_audit() -> Result:
    return _run(
        "contract-audit",
        [str(PYTHON), "-m", "app.scripts.audit_contracts"],
        BACKEND,
        timeout=300,
    )


def _step_contract_export() -> Result:
    return _drift_check(
        "contract-export",
        lambda: _run(
            "contract-export (generate)",
            [str(PYTHON), "-m", "app.scripts.export_contracts"],
            BACKEND,
            timeout=300,
        ),
        [OPENAPI],
    )


def _step_contract_types() -> Result:
    if not OPENAPI.is_file():
        return Result(
            "contract-types",
            "SKIP",
            "frontend/src/api/openapi.json is missing; run contract-export first",
        )

    def generate() -> Result:
        return _npm("contract-types (generate)", "gen:types", timeout=600)

    return _drift_check("contract-types", generate, [GENERATED_TYPES])


def _step_render_audit() -> Result:
    return _run(
        "render-audit",
        [str(PYTHON), "-m", "app.scripts.check_public_render"],
        BACKEND,
        timeout=300,
    )


def _step_docs_drift() -> Result:
    if not OPENAPI.is_file():
        return Result(
            "docs-drift",
            "SKIP",
            "frontend/src/api/openapi.json is missing; run contract-export first",
        )

    def generate() -> Result:
        return _run(
            "docs-drift (generate)",
            [str(PYTHON), "-m", "app.scripts.gen_docs"],
            BACKEND,
            timeout=300,
        )

    return _drift_check("docs-drift", generate, [SCHEMA_DOC, API_DOC])


def _step_frontend_check() -> Result:
    return _npm("frontend-check", "check", timeout=900)


def _step_frontend_lint() -> Result:
    result = _npm("frontend-lint", "lint", timeout=900)
    if result.status == "PASS":
        match = LINT_SUMMARY.search(result.output)
        if match:
            total, errors, warnings = match.groups()
            result.detail = f"{total} problems ({errors} errors, {warnings} warnings)"
        else:
            result.detail = "clean"
    return result


def _step_frontend_build() -> Result:
    return _npm("frontend-build", "build", timeout=1800)


_STEP_BUILDERS: dict[str, Callable[[], Result]] = {
    "backend-ruff": _step_backend_ruff,
    "backend-mypy": _step_backend_mypy,
    "backend-pytest": _step_backend_pytest,
    "contract-audit": _step_contract_audit,
    "contract-export": _step_contract_export,
    "contract-types": _step_contract_types,
    "render-audit": _step_render_audit,
    "docs-drift": _step_docs_drift,
    "frontend-check": _step_frontend_check,
    "frontend-lint": _step_frontend_lint,
    "frontend-build": _step_frontend_build,
    "smoke": _smoke,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selected_steps(args: argparse.Namespace) -> list[str]:
    if args.only:
        requested: list[str] = []
        for item in args.only:
            requested.extend(part.strip() for part in item.split(",") if part.strip())
        unknown = [name for name in requested if name not in STEPS]
        if unknown:
            raise SystemExit(
                f"unknown step(s): {', '.join(unknown)}. "
                f"Valid steps: {', '.join(STEPS)}"
            )
        return [name for name in STEPS if name in set(requested)]
    selected = [name for name in STEPS if name != "smoke"]
    if not args.no_smoke:
        selected.append("smoke")
    if args.skip_slow:
        selected = [name for name in selected if not STEPS[name]]
    return selected


def _format_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s"


def _print_table(results: list[Result]) -> None:
    rows = [
        (
            result.name,
            result.status,
            _format_seconds(result.seconds),
            result.detail.replace("\n", " | "),
        )
        for result in results
    ]
    headers = ("Step", "Result", "Time", "Detail")
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    print()
    print(separator)
    print(
        "| "
        + " | ".join(headers[index].ljust(widths[index]) for index in range(len(headers)))
        + " |"
    )
    print(separator)
    for row in rows:
        print(
            "| "
            + " | ".join(row[index].ljust(widths[index]) for index in range(len(headers)))
            + " |"
        )
    print(separator)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # keep Windows consoles from crashing
        with contextlib.suppress(OSError):
            sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(
        description=" MZTLAB 3.0.0 one-command acceptance run",
    )
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        help="skip mypy, pytest and the frontend production build",
    )
    smoke_group = parser.add_mutually_exclusive_group()
    smoke_group.add_argument(
        "--no-smoke",
        action="store_true",
        help="do not boot uvicorn for the runtime smoke test",
    )
    smoke_group.add_argument(
        "--smoke",
        action="store_true",
        help="force the runtime smoke step (it is on by default)",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="STEP[,STEP...]",
        help="run only the given step(s); may be repeated",
    )
    parser.add_argument("--list", action="store_true", help="list step names and exit")
    args = parser.parse_args(argv)

    if args.list:
        for name, slow in STEPS.items():
            print(f"{name:18s} {'slow' if slow else 'fast'}")
        return 0

    selected = _selected_steps(args)
    if not selected:
        print("No steps selected.")
        return 0

    print("MZTLAB 3.0.0 acceptance run")
    print(f"  root:   {ROOT}")
    print(f"  python: {PYTHON}")
    print(f"  steps:  {', '.join(selected)}")
    print()

    results: list[Result] = []
    for name in selected:
        print(f"[run]  {name} ...", flush=True)
        result = _STEP_BUILDERS[name]()
        results.append(result)
        icon = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}[result.status]
        print(
            f"[{icon}] {name} ({_format_seconds(result.seconds)})"
            + (f" - {result.detail.splitlines()[0]}" if result.detail else ""),
            flush=True,
        )

    _print_table(results)

    failures = [result for result in results if result.status == "FAIL"]
    for failure in failures:
        print()
        print(f"=== FAIL {failure.name} ===")
        if failure.command:
            print(f"command: {failure.command}")
        if failure.detail:
            print(failure.detail)
        if failure.output.strip():
            lines = failure.output.strip().splitlines()
            print("--- output (last 40 lines) ---")
            for line in lines[-40:]:
                print(line)

    passed = sum(1 for result in results if result.status == "PASS")
    skipped = sum(1 for result in results if result.status == "SKIP")
    print()
    print(
        f"Summary: {passed} passed, {len(failures)} failed, {skipped} skipped"
        f" / {len(results)} step(s)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

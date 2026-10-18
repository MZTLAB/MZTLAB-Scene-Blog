#!/usr/bin/env python3
"""Run the FastAPI backend and the Astro server together.

Examples:
    python scripts/run.py --dev
    python scripts/run.py
    python scripts/run.py --open
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"


def load_env_file() -> None:
    """Load simple KEY=VALUE pairs from the repo .env for the child processes."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def python_path() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def npm_command(args: list[str]) -> list[str]:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("找不到 npm，请先运行 python scripts/setup.py")
    if os.name == "nt":
        # Avoid cmd.exe quoting problems: run npm's JS entry with node directly.
        node = shutil.which("node")
        cli = Path(npm).with_name("node_modules") / "npm" / "bin" / "npm-cli.js"
        if node and cli.exists():
            return [node, str(cli), *args]
        command = subprocess.list2cmdline([npm, *args])
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f'"{command}"']
    return [npm, *args]


def terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


def wait_for_http(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5):
                return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MZTLAB locally")
    parser.add_argument("--dev", action="store_true", help="use Astro dev server with HMR")
    parser.add_argument("--reload", action="store_true", help="restart FastAPI on file changes")
    parser.add_argument("--open", action="store_true", help="open the site in a browser")
    parser.add_argument("--no-build", action="store_true", help="do not build before production start")
    args = parser.parse_args()

    load_env_file()

    python = python_path()
    if not python.exists():
        raise SystemExit("Python 环境不存在，请先运行：python scripts/setup.py")
    if not (FRONTEND / "node_modules").exists():
        raise SystemExit("前端依赖不存在，请先运行：python scripts/setup.py")

    backend_port = os.environ.get("BLOG_BACKEND_PORT", "8000")
    frontend_port = os.environ.get("BLOG_FRONTEND_PORT", "4321")
    internal_api = os.environ.get("BLOG_API_INTERNAL_URL", f"http://127.0.0.1:{backend_port}")

    env = os.environ.copy()
    env["BLOG_API_INTERNAL_URL"] = internal_api
    env["BLOG_FRONTEND_URL"] = f"http://127.0.0.1:{frontend_port}"
    env.setdefault("HOST", "127.0.0.1")
    env["PORT"] = frontend_port

    if not args.dev:
        entry = FRONTEND / "dist" / "server" / "entry.mjs"
        if not args.no_build:
            print("构建 Astro 生产版本 …", flush=True)
            subprocess.check_call(npm_command(["run", "build"]), cwd=FRONTEND, env=env)
        if not entry.exists():
            raise SystemExit("找不到 dist/server/entry.mjs，请先运行 npm run build。")

    backend_cmd = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        backend_port,
    ]
    if args.reload:
        backend_cmd.insert(-4, "--reload")
    frontend_cmd = (
        npm_command(["run", "dev", "--", "--host", "127.0.0.1", "--port", frontend_port])
        if args.dev
        else ["node", "dist/server/entry.mjs"]
    )

    print("\n" + "═" * 54, flush=True)
    print("  MZTLAB · Scene", flush=True)
    print(f"  Site     http://127.0.0.1:{frontend_port}", flush=True)
    print(f"  Admin    http://127.0.0.1:{frontend_port}/admin", flush=True)
    print(f"  API      {internal_api}/api/docs", flush=True)
    print(f"  Mode     {'development' if args.dev else 'production'}", flush=True)
    print("═" * 54 + "\n", flush=True)

    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None
    try:
        backend = subprocess.Popen(backend_cmd, cwd=BACKEND, env=env)
        if not wait_for_http(f"http://127.0.0.1:{backend_port}/api/health", timeout=25):
            print("后端没有及时启动，请检查上方日志。", flush=True)
        frontend = subprocess.Popen(frontend_cmd, cwd=FRONTEND, env=env)

        if args.open:
            time.sleep(2.0)
            webbrowser.open(f"http://127.0.0.1:{frontend_port}/")

        while True:
            if backend.poll() is not None:
                raise SystemExit(f"后端进程退出（code {backend.returncode}）")
            if frontend.poll() is not None:
                raise SystemExit(f"前端进程退出（code {frontend.returncode}）")
            time.sleep(0.8)
    except KeyboardInterrupt:
        print("\n正在停止 …")
        return 0
    finally:
        for proc in (frontend, backend):
            if proc is not None:
                terminate(proc)


if __name__ == "__main__":
    # Let Ctrl+C reach the finally block on Unix and Windows.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())

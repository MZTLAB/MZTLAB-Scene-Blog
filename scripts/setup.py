#!/usr/bin/env python3
"""Install backend and frontend dependencies with one command."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"


def run(command: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(command)}")
    subprocess.check_call(command, cwd=cwd)


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def check_node() -> None:
    node = shutil.which("node")
    if not node:
        raise SystemExit("找不到 node。请安装 Node.js 22.22 或更高版本：https://nodejs.org/")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    major, minor = (int(part) for part in version.lstrip("v").split(".")[:2])
    if major < 22 or (major == 22 and minor < 22):
        raise SystemExit(f"Node.js 版本过低（{version}）。Astro 7 需要 22.22 或更高版本。")
    print(f"Node.js {version} ✓")


def pip_available(python: Path) -> bool:
    try:
        subprocess.check_output(
            [str(python), "-m", "pip", "--version"],
            cwd=BACKEND,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def ensure_pip(python: Path) -> None:
    """Make sure the venv has pip.

    Debian/Ubuntu split ``ensurepip`` into a separate package and some servers
    end up with a venv created without pip. Repair it instead of failing.
    """
    if pip_available(python):
        return
    print("\n虚拟环境里没有 pip，正在修复 …")
    result = subprocess.run(
        [str(python), "-m", "ensurepip", "--upgrade"],
        cwd=BACKEND,
        check=False,
    )
    if result.returncode == 0 and pip_available(python):
        print("pip 修复完成 ✓")
        return

    url = "https://bootstrap.pypa.io/get-pip.py"
    print(f"ensurepip 不可用，改为从 {url} 安装 pip …")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            bootstrap = Path(tmp) / "get-pip.py"
            urllib.request.urlretrieve(url, bootstrap)
            run([str(python), str(bootstrap), "--disable-pip-version-check"], BACKEND)
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(
            "无法为虚拟环境安装 pip。\n"
            "Debian/Ubuntu 请先安装：sudo apt install python3-venv python3-pip\n"
            f"详细错误：{error}"
        ) from error
    if not pip_available(python):
        raise SystemExit(
            "pip 仍未安装成功。请安装 python3-venv 后删除 backend/.venv 再重试，"
            "或检查服务器是否能访问 bootstrap.pypa.io。"
        )
    print("pip 修复完成 ✓")


def create_venv() -> None:
    print("创建 Python 虚拟环境 …")
    try:
        venv.EnvBuilder(with_pip=True).create(VENV)
    except Exception as error:  # ensurepip missing on slim Debian images
        print(f"创建带 pip 的虚拟环境失败（{error}），改为稍后单独安装 pip …")
        shutil.rmtree(VENV, ignore_errors=True)
        venv.EnvBuilder(with_pip=False).create(VENV)


def install_backend() -> None:
    if not VENV.exists():
        create_venv()
    python = venv_python()
    if not python.exists():
        raise SystemExit(
            "虚拟环境不可用（找不到 Python 可执行文件）。\n"
            "请删除 backend/.venv 后重新运行 python scripts/setup.py。"
        )
    ensure_pip(python)
    run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND)
    print("Python 依赖安装完成 ✓")


def npm_command(args: list[str]) -> list[str]:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("找不到 npm，请先安装 Node.js。")
    if os.name == "nt":
        node = shutil.which("node")
        cli = Path(npm).with_name("node_modules") / "npm" / "bin" / "npm-cli.js"
        if node and cli.exists():
            return [node, str(cli), *args]
        command = subprocess.list2cmdline([npm, *args])
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f'"{command}"']
    return [npm, *args]


def install_frontend() -> None:
    if (FRONTEND / "package-lock.json").exists():
        run(npm_command(["ci", "--no-audit", "--no-fund"]), FRONTEND)
    else:
        run(npm_command(["install", "--no-audit", "--no-fund"]), FRONTEND)
    print("前端依赖安装完成 ✓")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install MZTLAB dependencies")
    parser.add_argument("--skip-backend", action="store_true", help="skip Python dependencies")
    parser.add_argument("--skip-frontend", action="store_true", help="skip Node dependencies")
    args = parser.parse_args()

    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 或更高版本。")
    print(f"Python {sys.version.split()[0]} ✓")
    check_node()

    if not args.skip_backend:
        install_backend()
    if not args.skip_frontend:
        install_frontend()

    print(
        "\n完成。接下来运行：\n"
        "  python scripts/run.py --dev     # 开发模式（热更新）\n"
        "  python scripts/run.py           # 生产模式（自动构建）\n"
        "\n首次打开 http://127.0.0.1:4321/admin/setup 创建管理员。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

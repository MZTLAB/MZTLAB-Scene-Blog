#!/usr/bin/env sh
# Thin POSIX wrapper for scripts/verify.py.
#
# Picks the backend virtualenv interpreter when present (so ruff/mypy/pytest
# and uvicorn resolve), falling back to python3/python on PATH.
#
#   sh scripts/verify.sh --skip-slow
#   ./scripts/verify.sh --only backend-pytest
#
# On Windows use scripts/verify.ps1 instead. This wrapper still works from
# Git Bash / WSL when a POSIX interpreter is available; if it has to call the
# Windows virtualenv python.exe it converts the repo path with cygpath/wslpath.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ -x "$ROOT/backend/.venv/bin/python" ]; then
    PYTHON="$ROOT/backend/.venv/bin/python"
elif [ -x "$ROOT/backend/.venv/Scripts/python.exe" ]; then
    PYTHON="$ROOT/backend/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    PYTHON=$(command -v python)
else
    echo "verify.sh: Python 3.11+ not found" >&2
    exit 2
fi

SCRIPT="$ROOT/scripts/verify.py"
case "$PYTHON" in
    *.exe)
        # Windows interpreter reached from a POSIX shell: hand it a
        # Windows-style path when the shell provides a converter.
        if command -v cygpath >/dev/null 2>&1; then
            SCRIPT=$(cygpath -w "$SCRIPT")
        elif command -v wslpath >/dev/null 2>&1; then
            SCRIPT=$(wslpath -w "$SCRIPT")
        fi
        ;;
esac

exec "$PYTHON" "$SCRIPT" "$@"

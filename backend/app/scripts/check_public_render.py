"""Static audit for SSG reserve R3 (render must not depend on request context).

Public pages are rendered from `page_data()` alone. Reading cookies, session,
user-agent, client address or arbitrary request headers would make a future
static build impossible, so this script fails when a public page/component
references them. Pagination must be path-based (R2), therefore `?page=` reads
are rejected too.

Run in CI: `python -m app.scripts.check_public_render`
"""

from __future__ import annotations

import re
from pathlib import Path

from ..config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend" / "src"

# Public pages + shared public components. Admin pages and non-HTML endpoints are
# SSR-only and intentionally excluded.
SCAN_DIRS = (FRONTEND / "pages", FRONTEND / "components", FRONTEND / "layouts")
EXCLUDE_PARTS = ("/admin/", "/api/")

FORBIDDEN: list[tuple[str, re.Pattern[str]]] = [
    ("Astro.request", re.compile(r"\bAstro\.request\b")),
    ("Astro.cookies", re.compile(r"\bAstro\.cookies\b")),
    ("Astro.clientAddress", re.compile(r"\bAstro\.clientAddress\b")),
    ("Astro.locals", re.compile(r"\bAstro\.locals\b")),
    ("cookie header", re.compile(r"headers?\.get\(\s*['\"]cookie", re.IGNORECASE)),
    ("user-agent", re.compile(r"user-agent", re.IGNORECASE)),
    ("query pagination", re.compile(r"searchParams\.get\(\s*['\"]page['\"]")),
]

# Files that are not public HTML pages (meta files rendered for crawlers).
EXCLUDE_FILES = {
    "rss.xml.ts",
    "sitemap.xml.ts",
    "robots.txt.ts",
    "middleware.ts",
}


def _files() -> list[Path]:
    result: list[Path] = []
    for directory in SCAN_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.suffix not in {".astro", ".ts"}:
                continue
            if path.name in EXCLUDE_FILES:
                continue
            relative = "/" + path.relative_to(FRONTEND).as_posix()
            if any(part in relative for part in EXCLUDE_PARTS):
                continue
            result.append(path)
    return result


def check() -> list[str]:
    violations: list[str] = []
    for path in _files():
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT_DIR).as_posix()
        for label, pattern in FORBIDDEN:
            for match in pattern.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                violations.append(f"{relative}:{line}: forbidden {label}")
    return violations


def main() -> int:
    violations = check()
    if violations:
        print("Public render audit failed (R3):")
        for violation in violations:
            print(f"  {violation}")
        print(
            "\nPublic pages must not read request context. Use /api/bootstrap and "
            "path-based pagination instead."
        )
        return 1
    print(f"Public render audit OK: {len(_files())} files, no request-context reads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

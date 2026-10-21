"""Build-time OpenAPI export.

    python -m app.scripts.export_contracts

Writes `frontend/src/api/openapi.json`; `npm run gen:types` turns it into
`frontend/src/api/types.gen.ts`. CI re-runs both and fails on `git diff`, so a
hand-edited frontend type or an undeclared response shape cannot drift.
"""

from __future__ import annotations

import json

from ..config import ROOT_DIR

OUTPUT = ROOT_DIR / "frontend" / "src" / "api" / "openapi.json"


def build_spec() -> dict:
    from ..main import app

    # The FastAPI instance keeps docs disabled in production; generating the
    # schema in-process does not expose anything.
    return app.openapi()


def main() -> int:
    spec = build_spec()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {OUTPUT} ({len(spec.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

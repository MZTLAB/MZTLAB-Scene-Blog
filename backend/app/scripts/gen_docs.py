"""Generate the schema and API reference documentation from code.

    python -m app.scripts.gen_docs

Produces:
* `docs/SCHEMA.md` — tables/columns/indexes/introspection of a database built
  from `backend/migrations/*.sql` (single source of truth; no hand-written field
  tables);
* `docs/API.md` — endpoint table generated from the exported `openapi.json`.

CI re-runs this and fails on `git diff --exit-code`, so docs cannot drift.
"""

from __future__ import annotations

import json
import sqlite3

from ..config import ROOT_DIR

MIGRATIONS = ROOT_DIR / "backend" / "migrations"
OPENAPI = ROOT_DIR / "frontend" / "src" / "api" / "openapi.json"
SCHEMA_DOC = ROOT_DIR / "docs" / "SCHEMA.md"
API_DOC = ROOT_DIR / "docs" / "API.md"

HEADER = "> 适用版本：3.0.0-beta3。本文件由脚本生成（`python -m app.scripts.gen_docs`），请勿手改。"


def _build_database() -> tuple[sqlite3.Connection, list[str]]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    applied: list[str] = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return conn, applied


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' "
            "ORDER BY name"
        )
    ]


def _columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"PRAGMA table_info({table})"))


def _foreign_keys(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"PRAGMA foreign_key_list({table})"))


def _indexes(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"PRAGMA index_list({table})"))


def render_schema() -> str:
    conn, applied = _build_database()
    lines: list[str] = [
        "# MZTLAB · Scene 数据库结构（3.0.0）",
        "",
        HEADER,
        "",
        "## 迁移文件",
        "",
        "| # | 文件 |",
        "| --- | --- |",
    ]
    for index, name in enumerate(applied, start=1):
        lines.append(f"| {index} | `{name}` |")
    lines.extend(["", "## 表", ""])
    for table in _table_names(conn):
        lines.extend(
            [
                f"### `{table}`",
                "",
                "| 列 | 类型 | 可空 | 默认值 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for column in _columns(conn, table):
            nullable = "否" if column["notnull"] else "是"
            default = column["dflt_value"] if column["dflt_value"] is not None else ""
            lines.append(
                f"| `{column['name']}` | {column['type'] or '—'} | {nullable} | "
                f"{('`' + str(default) + '`') if default else '—'} |"
            )
        foreign = _foreign_keys(conn, table)
        if foreign:
            lines.extend(["", "外键："])
            for fk in foreign:
                lines.append(
                    f"- `{fk['from']}` → `{fk['table']}.{fk['to']}`"
                    f"（ON DELETE {fk['on_delete']}）"
                )
        indexes = _indexes(conn, table)
        if indexes:
            lines.extend(["", "索引："])
            for index_row in indexes:
                if str(index_row["name"]).startswith("sqlite_autoindex"):
                    continue
                columns = [
                    str(info["name"])
                    for info in conn.execute(f"PRAGMA index_info({index_row['name']})")
                ]
                unique = "（唯一）" if index_row["unique"] else ""
                lines.append(f"- `{index_row['name']}`{unique}: {', '.join(columns)}")
        lines.append("")
    conn.close()
    return "\n".join(lines).rstrip() + "\n"


def _schema_name(schema: dict | None) -> str:
    if not schema:
        return "—"
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if "anyOf" in schema or "oneOf" in schema:
        key = "anyOf" if "anyOf" in schema else "oneOf"
        return " / ".join(_schema_name(item) for item in schema[key])
    if schema.get("type") == "array":
        return f"array<{_schema_name(schema.get('items'))}>"
    return str(schema.get("type") or "—")


def render_api() -> str:
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    lines: list[str] = [
        "# MZTLAB · Scene API 参考（3.0.0）",
        "",
        HEADER,
        "",
        f"OpenAPI `{spec['info'].get('version', '')}` · {len(spec.get('paths', {}))} 个路径 · "
        f"{len(spec.get('components', {}).get('schemas', {}))} 个数据模型",
        "",
        "鉴权：除 `/api/site`、`/api/bootstrap`、`/api/posts*`、`/api/pages*`、`/api/projects*`、"
        "`/api/galleries*`、`/api/archive`、`/api/search`、`/api/taxonomy`、`/api/health*`、"
        "`/api/auth/login`、`/api/setup` 外，均需登录；`/api/admin/*` 的写请求还需要 "
        "`X-Blog-Request: 1` 头。",
        "",
        "## 端点",
        "",
        "| 方法 | 路径 | 说明 | 2xx 响应模型 |",
        "| --- | --- | --- | --- |",
    ]
    methods = {"get", "post", "put", "patch", "delete"}
    for path, operations in sorted(spec.get("paths", {}).items()):
        for method, operation in operations.items():
            if method not in methods:
                continue
            responses = operation.get("responses", {})
            schema = None
            for status in ("200", "201", "202"):
                content = (responses.get(status) or {}).get("content", {})
                if content:
                    schema = next(iter(content.values())).get("schema")
                    break
            summary = str(operation.get("summary") or operation.get("operationId") or "")
            lines.append(
                f"| {method.upper()} | `{path}` | {summary} | {_schema_name(schema)} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    SCHEMA_DOC.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_DOC.write_text(render_schema(), encoding="utf-8", newline="\n")
    API_DOC.write_text(render_api(), encoding="utf-8", newline="\n")
    print(f"wrote {SCHEMA_DOC}")
    print(f"wrote {API_DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

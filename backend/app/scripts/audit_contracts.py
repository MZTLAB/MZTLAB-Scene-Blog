"""OpenAPI contract audit.

    python -m app.scripts.audit_contracts

Fails (exit code 1) when the generated spec drifts from the 3.0.0 contract:

* any `/api` operation whose 2xx JSON response is not a named `$ref`
  (i.e. a loose inline object / `additionalProperties: true`), and
* any `additionalProperties: true` anywhere in the spec.

Binary endpoints (`/media/...`) intentionally have no JSON schema and are
skipped: they are not part of the JSON contract.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

# Responses served by `app.routes.media_serve` are files/redirects, never JSON.
BINARY_PATH_PREFIXES = ("/media/",)


def _iter_dicts(value: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _iter_dicts(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_dicts(child, f"{path}/{index}")


def _schema_ref(schema: dict[str, Any]) -> str | None:
    """Return the referenced schema name for a response schema, if named."""
    if "$ref" in schema:
        return str(schema["$ref"])
    for key in ("allOf", "anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list) and len(options) == 1:
            return _schema_ref(options[0])
    return None


def is_binary_path(path: str) -> bool:
    return path.startswith(BINARY_PATH_PREFIXES)


def loose_responses(spec: dict[str, Any]) -> list[str]:
    """2xx JSON responses that are not a named `$ref`."""
    problems: list[str] = []
    for path, operations in sorted(spec.get("paths", {}).items()):
        if not path.startswith("/api") or is_binary_path(path):
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith("2"):
                    continue
                for media_type, media in response.get("content", {}).items():
                    if "json" not in media_type:
                        continue
                    schema = media.get("schema") or {}
                    if _schema_ref(schema) is None:
                        problems.append(
                            f"{method.upper()} {path} {status}: "
                            f"{media_type} is not a named $ref ({schema})"
                        )
    return problems


def additional_properties_true(spec: dict[str, Any]) -> list[str]:
    """Every location in the spec that still allows free-form properties."""
    problems: list[str] = []
    for path, node in _iter_dicts(spec):
        if node.get("additionalProperties") is True:
            problems.append(path)
    return problems


def main() -> int:
    from ..main import app

    spec = app.openapi()
    loose = loose_responses(spec)
    free = additional_properties_true(spec)

    paths = len(spec.get("paths", {}))
    schemas = len(spec.get("components", {}).get("schemas", {}))
    print(f"OpenAPI: {paths} paths, {schemas} schemas")

    for problem in loose:
        print(f"[loose 2xx] {problem}")
    for problem in free:
        print(f"[additionalProperties: true] {problem}")

    if loose or free:
        print(
            f"FAIL: {len(loose)} loose 2xx response(s), "
            f"{len(free)} additionalProperties: true node(s)"
        )
        return 1
    print("OK: every 2xx JSON response is a named $ref; no free-form objects")
    return 0


if __name__ == "__main__":
    sys.exit(main())

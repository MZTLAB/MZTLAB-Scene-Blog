"""Unified API error envelope.

Every error response has the same shape:

    {"error": {"code": "content.slug_taken", "message": "别名已被占用",
               "field": "slug"}}

`code` is stable and machine-readable; `message` is a developer-facing Chinese
fallback and the single source of UI copy is the frontend (i18n). Routers raise
`ApiError` (or plain `HTTPException`, which is mapped to a generic code).
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException

CODE_BY_STATUS = {
    400: "request.invalid",
    401: "auth.required",
    403: "auth.forbidden",
    404: "resource.not_found",
    405: "request.method_not_allowed",
    409: "resource.conflict",
    413: "request.too_large",
    415: "request.unsupported_media_type",
    422: "request.validation_failed",
    429: "rate_limit.exceeded",
    500: "server.internal_error",
}


class ApiError(HTTPException):
    """HTTPException carrying a stable error code and optional field name."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.field = field


def error_payload(
    code: str, message: str, field: str | None = None
) -> dict[str, dict[str, str]]:
    error: dict[str, str] = {"code": code, "message": message}
    if field:
        error["field"] = field
    return {"error": error}


def from_http_exception(exc: StarletteHTTPException) -> dict[str, dict[str, str]]:
    message = exc.detail if isinstance(exc.detail, str) else "请求失败"
    code = getattr(exc, "code", None) or CODE_BY_STATUS.get(
        exc.status_code, "server.internal_error"
    )
    field = getattr(exc, "field", None)
    return error_payload(code, message, field)

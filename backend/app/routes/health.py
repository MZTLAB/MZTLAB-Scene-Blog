"""Liveness plus an ingress self-check endpoint.

The access layer (nginx) is maintained by operations and is not part of this
repository, so "is the ingress configured correctly?" is answered at runtime:
`GET /api/health/edge` reports what the application actually observes for the
caller (effective client IP, forwarded protocol, request id). The staging
checklist in `docs/EDGE.md` curls this endpoint behind the real ingress.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..api.models import EdgeHealthResponse
from ..config import COOKIE_SECURE, TRUSTED_PROXY
from ..deps import client_ip

router = APIRouter(tags=["health"])


@router.get("/health/edge", response_model=EdgeHealthResponse)
def edge_health(request: Request) -> dict[str, object]:
    return {
        "ok": True,
        # The address rate limiting/audit logs will use. Only the trusted
        # ingress can influence it (uvicorn --proxy-headers).
        "client_ip": client_ip(request),
        # Raw headers, so operations can verify the ingress overwrites (rather
        # than appends to) X-Forwarded-For / X-Forwarded-Proto.
        "forwarded_for": request.headers.get("x-forwarded-for"),
        "forwarded_proto": request.headers.get("x-forwarded-proto"),
        "request_id": getattr(request.state, "request_id", ""),
        "trusted_proxy": TRUSTED_PROXY,
        "cookie_secure": COOKIE_SECURE,
    }

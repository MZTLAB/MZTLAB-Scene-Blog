"""Service layer (3.0.0).

Routers stay thin: HTTP concerns and dependency wiring. Business rules that are
shared or need unit tests live here.
"""

from .authz import authorize, authorize_photo, owns

__all__ = ["authorize", "authorize_photo", "owns"]

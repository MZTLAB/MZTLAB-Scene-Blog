from __future__ import annotations

import unittest

from app.errors import ApiError
from app.permissions import (
    PERMISSIONS,
    ROLE_PERMISSIONS,
    can,
    effective_permissions,
    is_staff,
    normalize_role,
    permissions_for,
    role_meta,
)
from app.services.authz import authorize, owns


def session(role: str, *, manage_others: bool = False, **extra: object) -> dict:
    user = {
        "id": extra.pop("id", 1),
        "role": role,
        "permissions": effective_permissions(role, manage_others=manage_others),
        **extra,
    }
    return user


class PermissionTests(unittest.TestCase):
    def test_admin_has_every_permission(self) -> None:
        self.assertEqual(set(ROLE_PERMISSIONS["admin"]), set(PERMISSIONS))
        self.assertTrue(can(session("admin"), "users.manage"))
        self.assertTrue(can(session("admin"), "settings.manage"))
        self.assertNotIn("comment.moderate", PERMISSIONS)

    def test_editor_manages_own_content_by_default(self) -> None:
        editor = session("editor")
        self.assertFalse(can(editor, "content.others"))
        self.assertTrue(can(editor, "content.delete"))
        self.assertFalse(can(editor, "settings.manage"))
        self.assertFalse(can(editor, "users.manage"))

    def test_editor_can_be_widened_by_the_site_setting(self) -> None:
        editor = session("editor", manage_others=True)
        self.assertTrue(can(editor, "content.others"))
        self.assertTrue(can(editor, "media.manage"))
        # Authors never inherit the switch.
        self.assertNotIn(
            "content.others",
            effective_permissions("author", manage_others=True),
        )

    def test_permissions_only_come_from_the_session_list(self) -> None:
        # 3.0.0 removed the role-dict fallback: a bare role name grants nothing,
        # so a missing permission list cannot silently elevate a caller.
        self.assertFalse(can({"role": "admin"}, "users.manage"))
        self.assertTrue(can({"role": "admin", "permissions": ["users.manage"]}, "users.manage"))

    def test_author_is_limited_to_own_work(self) -> None:
        author = session("author")
        self.assertTrue(can(author, "content.write"))
        self.assertTrue(can(author, "content.publish"))
        self.assertFalse(can(author, "content.others"))
        self.assertFalse(can(author, "content.delete"))

    def test_inactive_or_anonymous_users_have_nothing(self) -> None:
        self.assertFalse(can(None, "content.read"))
        inactive = {"role": "admin", "is_active": False, "permissions": ["content.read"]}
        self.assertFalse(can(inactive, "content.read"))
        self.assertFalse(is_staff(None))

    def test_unknown_roles_fall_back_to_author(self) -> None:
        self.assertEqual(normalize_role("root"), "author")
        self.assertEqual(normalize_role("ADMIN"), "admin")
        self.assertEqual(permissions_for("root"), permissions_for("author"))

    def test_role_meta_is_shaped_for_the_ui(self) -> None:
        meta = role_meta()
        self.assertEqual([item["key"] for item in meta], ["admin", "editor", "author"])
        for item in meta:
            self.assertTrue(item["label"])
            self.assertTrue(item["summary"])
            self.assertTrue(item["permissions"])


class OwnershipTests(unittest.TestCase):
    def test_owner_id_is_the_only_ownership_column(self) -> None:
        user = session("author", id=3)
        self.assertTrue(owns(user, {"owner_id": 3}))
        self.assertFalse(owns(user, {"owner_id": 4}))
        # Legacy columns are ignored, not guessed.
        self.assertFalse(owns(user, {"author_id": 3}))
        self.assertFalse(owns(user, {"uploaded_by": 3}))
        self.assertFalse(owns(user, {"owner_id": None}))

    def test_authorize_allows_owner_and_content_others(self) -> None:
        owner = session("author", id=3)
        authorize(owner, {"owner_id": 3})
        manager = session("editor", id=9, manage_others=True)
        authorize(manager, {"owner_id": 3})
        outsider = session("author", id=4)
        with self.assertRaises(ApiError) as raised:
            authorize(outsider, {"owner_id": 3})
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.code, "auth.ownership_required")

    def test_authorize_rejects_missing_resource(self) -> None:
        with self.assertRaises(ApiError) as raised:
            authorize(session("admin"), None)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

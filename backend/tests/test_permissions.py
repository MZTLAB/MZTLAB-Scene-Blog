from __future__ import annotations

import unittest

from app.permissions import (
    PERMISSIONS,
    ROLE_PERMISSIONS,
    can,
    effective_permissions,
    is_staff,
    normalize_role,
    owns,
    permissions_for,
    role_meta,
)


class PermissionTests(unittest.TestCase):
    def test_admin_has_every_permission(self) -> None:
        self.assertEqual(set(ROLE_PERMISSIONS["admin"]), set(PERMISSIONS))
        self.assertTrue(can({"role": "admin"}, "users.manage"))
        self.assertTrue(can({"role": "admin"}, "settings.manage"))

    def test_editor_manages_own_content_by_default(self) -> None:
        editor = {"role": "editor"}
        self.assertFalse(can(editor, "content.others"))
        self.assertTrue(can(editor, "content.delete"))
        self.assertTrue(can(editor, "comment.moderate"))
        self.assertFalse(can(editor, "settings.manage"))
        self.assertFalse(can(editor, "users.manage"))

    def test_editor_can_be_widened_by_the_site_setting(self) -> None:
        editor = {
            "role": "editor",
            "permissions": effective_permissions("editor", manage_others=True),
        }
        self.assertTrue(can(editor, "content.others"))
        self.assertTrue(can(editor, "media.manage"))
        # Authors never inherit the switch.
        self.assertNotIn(
            "content.others",
            effective_permissions("author", manage_others=True),
        )

    def test_session_permissions_override_the_static_table(self) -> None:
        # A session list is authoritative so a revoked permission applies at
        # the next request, without waiting for the role table to change.
        session = {"role": "editor", "permissions": ["content.read", "content.write"]}
        self.assertTrue(can(session, "content.write"))
        self.assertFalse(can(session, "content.others"))

    def test_author_is_limited_to_own_work(self) -> None:
        author = {"role": "author"}
        self.assertTrue(can(author, "content.write"))
        self.assertTrue(can(author, "content.publish"))
        self.assertFalse(can(author, "content.others"))
        self.assertFalse(can(author, "content.delete"))
        self.assertFalse(can(author, "comment.moderate"))

    def test_inactive_or_anonymous_users_have_nothing(self) -> None:
        self.assertFalse(can(None, "content.read"))
        self.assertFalse(can({"role": "admin", "is_active": False}, "content.read"))
        self.assertFalse(is_staff(None))

    def test_unknown_roles_fall_back_to_author(self) -> None:
        self.assertEqual(normalize_role("root"), "author")
        self.assertEqual(normalize_role("ADMIN"), "admin")
        self.assertEqual(permissions_for("root"), permissions_for("author"))

    def test_ownership(self) -> None:
        user = {"id": 3, "role": "author"}
        self.assertTrue(owns(user, {"author_id": 3}))
        self.assertFalse(owns(user, {"author_id": 4}))
        self.assertTrue(owns(user, {"owner_id": 3}))
        self.assertTrue(owns(user, {"uploaded_by": 3}))
        self.assertFalse(owns(user, {"owner_id": 4, "uploaded_by": 3}))
        self.assertFalse(owns(user, None))
        self.assertFalse(owns(user, {"author_id": None}))

    def test_role_meta_is_shaped_for_the_ui(self) -> None:
        meta = role_meta()
        self.assertEqual([item["key"] for item in meta], ["admin", "editor", "author"])
        for item in meta:
            self.assertTrue(item["label"])
            self.assertTrue(item["summary"])
            self.assertTrue(item["permissions"])


if __name__ == "__main__":
    unittest.main()

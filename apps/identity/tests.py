"""
Tests for identity views, user administration, and security boundaries.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class UserAdministrationViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_id", password="pw", role="ADMIN")
        self.member = User.objects.create_user(username="member_id", password="pw", role="MEMBER")

        self.client_admin = Client()
        self.client_admin.force_login(self.admin)

        self.client_member = Client()
        self.client_member.force_login(self.member)

    def test_user_list_admin_only(self):
        # Non-admin forbidden
        r_member = self.client_member.get(reverse("user_list"))
        self.assertEqual(r_member.status_code, 403)

        # Admin allowed
        r_admin = self.client_admin.get(reverse("user_list"))
        self.assertEqual(r_admin.status_code, 200)
        self.assertContains(r_admin, "admin_id")
        self.assertContains(r_admin, "member_id")

    def test_user_create_admin_only(self):
        # Non-admin forbidden
        r_member = self.client_member.get(reverse("user_create"))
        self.assertEqual(r_member.status_code, 403)

        # Admin creates user
        r_admin = self.client_admin.post(reverse("user_create"), {
            "username": "new_household_member",
            "password": "ValidPassword123!",
            "role": "MEMBER",
        })
        self.assertEqual(r_admin.status_code, 302)
        self.assertTrue(User.objects.filter(username="new_household_member").exists())

    def test_user_edit_and_self_demotion_safeguard(self):
        # Edit existing member
        r_edit = self.client_admin.post(reverse("user_edit", kwargs={"pk": self.member.pk}), {
            "username": self.member.username,
            "role": "MEMBER",
            "is_active": True,
        })
        self.assertEqual(r_edit.status_code, 302)

        # Admin attempts to demote self -> blocked
        r_self = self.client_admin.post(reverse("user_edit", kwargs={"pk": self.admin.pk}), {
            "username": self.admin.username,
            "role": "MEMBER",
            "is_active": True,
        })
        self.assertEqual(r_self.status_code, 200)
        self.assertContains(r_self, "cannot deactivate or demote your own")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "ADMIN")

    def test_user_toggle_active_safeguard(self):
        # Admin cannot deactivate self
        r_self = self.client_admin.post(reverse("user_toggle_active", kwargs={"pk": self.admin.pk}))
        self.assertEqual(r_self.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

        # Admin deactivates member
        r_toggle = self.client_admin.post(reverse("user_toggle_active", kwargs={"pk": self.member.pk}))
        self.assertEqual(r_toggle.status_code, 302)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

        # Admin reactivates member
        r_toggle2 = self.client_admin.post(reverse("user_toggle_active", kwargs={"pk": self.member.pk}))
        self.assertEqual(r_toggle2.status_code, 302)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

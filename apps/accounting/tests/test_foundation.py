import os
from decimal import Decimal
from unittest.mock import patch

import psycopg
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounting.models import Account, AccountGrant, JournalEntry, JournalLine, LedgerSettings
from apps.accounting.policies import can_edit_draft, can_post_to_account, can_view_entry, visible_accounts

User = get_user_model()


def make_account(code, **kwargs):
    values = dict(code=code, name=code, classical_type="REAL", reporting_class="ASSET", normal_side="DEBIT")
    values.update(kwargs)
    return Account.objects.create(**values)


class VisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="admin", password="test-password", role="ADMIN")
        cls.alice = User.objects.create_user(username="alice", password="test-password")
        cls.bob = User.objects.create_user(username="bob", password="test-password")
        cls.shared = make_account("SHARED")
        cls.alice_bank = make_account("ALICE", visibility="PERSONAL", owner=cls.alice)
        cls.bob_bank = make_account("BOB", visibility="PERSONAL", owner=cls.bob)

    def test_shared_view_does_not_grant_posting(self):
        self.assertIn(self.shared, visible_accounts(self.alice))
        self.assertFalse(can_post_to_account(self.alice, self.shared))
        self.assertTrue(can_post_to_account(self.alice, self.alice_bank))
        self.assertNotIn(self.bob_bank, visible_accounts(self.alice))

    def test_explicit_grant_then_revocation(self):
        grant = AccountGrant.objects.create(user=self.alice, account=self.bob_bank, can_view=True, can_post=True)
        self.assertTrue(can_post_to_account(self.alice, self.bob_bank))
        grant.delete()
        self.assertNotIn(self.bob_bank, visible_accounts(self.alice))

    def test_mixed_entry_cannot_be_viewed_even_by_creator(self):
        entry = JournalEntry.objects.create(creator=self.alice)
        JournalLine.objects.create(entry=entry, line_number=1, account=self.shared, debit=Decimal("10"))
        JournalLine.objects.create(entry=entry, line_number=2, account=self.bob_bank, credit=Decimal("10"))
        self.assertFalse(can_view_entry(self.alice, entry))
        self.assertFalse(can_edit_draft(self.alice, entry))
        self.assertTrue(can_view_entry(self.admin, entry))

    def test_inactive_actor_sees_nothing(self):
        self.alice.is_active = False
        self.assertFalse(visible_accounts(self.alice).exists())
        self.assertFalse(can_post_to_account(self.alice, self.alice_bank))

    def test_inactive_or_group_accounts_are_not_postable(self):
        self.shared.is_group = True
        self.shared.save()
        self.assertFalse(can_post_to_account(self.admin, self.shared))
        self.alice_bank.is_active = False
        self.alice_bank.save()
        self.assertFalse(can_post_to_account(self.alice, self.alice_bank))

    def test_login_dashboard_and_csrf_logout(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, "/login/?next=/")
        self.assertTrue(self.client.login(username="alice", password="test-password"))
        page = self.client.get(reverse("home"))
        self.assertContains(page, "ALICE")
        self.assertNotContains(page, "BOB")
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)

    def test_health_does_not_expose_failure_details(self):
        with patch("apps.operations.views.connection.cursor", side_effect=DatabaseError("private connection details")):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})


class ConstraintTests(TestCase):
    def test_superuser_is_household_admin(self):
        user = User.objects.create_superuser(username="owner", password="test-password")
        self.assertEqual(user.role, "ADMIN")

    def test_account_group_cycle_and_class_mismatch(self):
        group = make_account("GROUP", is_group=True)
        leaf = make_account("LEAF", parent=group)
        group.parent = leaf
        with self.assertRaises(ValidationError):
            group.full_clean()

    def test_personal_account_cannot_lack_owner_in_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_account("INVALID", visibility="PERSONAL")

    def test_posting_grant_requires_view_in_database(self):
        member = User.objects.create_user(username="member")
        account = make_account("CASH")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountGrant.objects.create(user=member, account=account, can_view=False, can_post=True)

    def test_money_side_constraint(self):
        member = User.objects.create_user(username="member")
        entry = JournalEntry.objects.create(creator=member)
        account = make_account("CASH")
        for debit, credit in [(0, 0), (10, 10), (-1, 0)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                JournalLine.objects.create(entry=entry, line_number=1, account=account, debit=debit, credit=credit)

    def test_single_book_and_currency(self):
        LedgerSettings.objects.get_or_create(pk=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerSettings.objects.create(pk=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerSettings.objects.filter(pk=1).update(currency="USD")


class RuntimeRoleTests(TransactionTestCase):
    def test_runtime_has_dml_but_cannot_create_schema_objects(self):
        conn = psycopg.connect(os.environ["TEST_RUNTIME_DATABASE_URL"])
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_user")
                self.assertEqual(cursor.fetchone()[0], "ledger_test_app")
                cursor.execute("INSERT INTO accounting_ledgersettings "
                               "(id,name,currency,timezone_name,fiscal_start_month,fiscal_start_day) "
                               "VALUES (1,'Test','INR','Asia/Kolkata',4,1) "
                               "ON CONFLICT (id) DO NOTHING")
                cursor.execute("SELECT name FROM accounting_ledgersettings WHERE id=1")
                self.assertIsNotNone(cursor.fetchone())
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("CREATE TABLE public.should_not_exist (id integer)")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("ALTER TABLE accounting_journalentry DISABLE TRIGGER ALL")
        finally:
            conn.close()


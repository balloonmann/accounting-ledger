"""
Milestone 3 Acceptance Tests: Privacy, Grants, Concurrency, and Administration.
Covers:
  - A08: Unauthorized IDs across forms, URLs, and queries cannot read/post.
  - A09: Mixed-visibility redaction holds across screen and errors.
  - A10: Concurrent reversal yields exactly one linked reversal.
  - A13: Lock-date changes and posting serialize cleanly; reason required.
  - A20: Coordinated permission/actor-state changes respected at posting boundary.
"""
import threading
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounting.choices import ClassicalType, EntryKind, EntryState, Purpose, ReportingClass, Side, Visibility
from apps.accounting.models import Account, AccountGrant, JournalEntry, JournalLine, LedgerSettings
from apps.accounting.services import (
    AuthorizationError,
    ConflictError,
    ServiceError,
    create_draft,
    post_entry,
    reverse_entry,
    set_account_grants,
    set_posting_lock_date,
    update_draft,
)
from apps.operations.models import ActivityRecord

User = get_user_model()


def make_account(code, name=None, **kwargs):
    defaults = {
        "classical_type": ClassicalType.REAL,
        "reporting_class": ReportingClass.ASSET,
        "purpose": Purpose.GENERAL,
        "normal_side": Side.DEBIT,
        "is_active": True,
        "is_group": False,
        "visibility": Visibility.SHARED,
    }
    defaults.update(kwargs)
    return Account.objects.create(code=code, name=name or f"Account {code}", **defaults)


# ---------------------------------------------------------------------------
# A08 — Unauthorized ID access across forms, URLs, and queries
# ---------------------------------------------------------------------------

class A08UnauthorizedAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="admin_a08", password="pw", role="ADMIN")
        cls.alice = User.objects.create_user(username="alice_a08", password="pw", role="MEMBER")
        cls.bob = User.objects.create_user(username="bob_a08", password="pw", role="MEMBER")

        LedgerSettings.objects.get_or_create(pk=1)

        cls.cash = make_account("CASH_08")
        cls.bob_private = make_account("BOB_PVT_08", visibility=Visibility.PERSONAL, owner=cls.bob)

        # Alice has posting grant on cash
        AccountGrant.objects.create(account=cls.cash, user=cls.alice, can_view=True, can_post=True)

    def setUp(self):
        self.client_alice = Client()
        self.client_alice.force_login(self.alice)
        self.client_bob = Client()
        self.client_bob.force_login(self.bob)

    def test_member_cannot_view_another_members_private_account_ledger(self):
        """Alice cannot view the ledger of Bob's private account (returns 404)."""
        response = self.client_alice.get(reverse("account_ledger", kwargs={"pk": self.bob_private.pk}))
        self.assertEqual(response.status_code, 404)

    def test_member_cannot_post_to_unauthorized_account(self):
        """Alice cannot post a draft touching Bob's private account."""
        draft = create_draft(
            self.admin,
            "2026-04-01",
            "Admin created draft with Bob's private account",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": Decimal("0.00")},
                {"account_id": self.bob_private.pk, "debit": Decimal("0.00"), "credit": Decimal("100.00")},
            ],
        )
        with self.assertRaises(AuthorizationError):
            post_entry(self.alice, draft, draft.version, uuid.uuid4())

    def test_member_cannot_edit_another_members_draft(self):
        """Alice cannot edit a draft created by Bob."""
        draft = create_draft(
            self.bob,
            "2026-04-01",
            "Bob draft",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("10.00"), "credit": Decimal("0.00")},
                {"account_id": self.bob_private.pk, "debit": Decimal("0.00"), "credit": Decimal("10.00")},
            ],
        )
        response = self.client_alice.get(reverse("draft_edit", kwargs={"pk": draft.pk}))
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_access_administrative_views(self):
        """Regular members cannot access admin-only views."""
        # Account Grants
        r1 = self.client_alice.get(reverse("account_grants", kwargs={"pk": self.cash.pk}))
        self.assertEqual(r1.status_code, 403)

        # Lock Date Settings
        r2 = self.client_alice.get(reverse("settings_lock_date"))
        self.assertEqual(r2.status_code, 403)

        # User List
        r3 = self.client_alice.get(reverse("user_list"))
        self.assertEqual(r3.status_code, 403)


# ---------------------------------------------------------------------------
# A09 — Mixed-visibility redaction holds across screen and errors
# ---------------------------------------------------------------------------

class A09MixedVisibilityRedactionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="admin_a09", password="pw", role="ADMIN")
        cls.alice = User.objects.create_user(username="alice_a09", password="pw", role="MEMBER")
        cls.bob = User.objects.create_user(username="bob_a09", password="pw", role="MEMBER")

        LedgerSettings.objects.get_or_create(pk=1)

        # Shared cash account visible to all
        cls.shared_cash = make_account("CASH_09", visibility=Visibility.SHARED)
        # Alice's private investment account visible only to Alice and Admin
        cls.alice_pvt = make_account("ALICE_INV_09", visibility=Visibility.PERSONAL, owner=cls.alice)

        AccountGrant.objects.create(account=cls.shared_cash, user=cls.alice, can_view=True, can_post=True)
        AccountGrant.objects.create(account=cls.shared_cash, user=cls.bob, can_view=True, can_post=True)

        # Post a mixed-visibility entry: Alice moves INR 750 from shared cash to her private investment
        cls.mixed_draft = create_draft(
            cls.alice,
            "2026-04-05",
            "Alice personal investment deposit",
            EntryKind.JOURNAL,
            [
                {"account_id": cls.alice_pvt.pk, "debit": Decimal("750.00"), "credit": Decimal("0.00")},
                {"account_id": cls.shared_cash.pk, "debit": Decimal("0.00"), "credit": Decimal("750.00")},
            ],
        )
        cls.mixed_entry = post_entry(cls.alice, cls.mixed_draft, 1, uuid.uuid4())

    def setUp(self):
        self.client_bob = Client()
        self.client_bob.force_login(self.bob)
        self.client_alice = Client()
        self.client_alice.force_login(self.alice)

    def test_full_entry_detail_denied_to_unauthorized_member(self):
        """Bob cannot view the full entry detail because he cannot view Alice's private account."""
        response = self.client_bob.get(reverse("entry_detail", kwargs={"pk": self.mixed_entry.pk}))
        self.assertEqual(response.status_code, 403)

    def test_mixed_visibility_redaction_on_shared_account_ledger(self):
        """
        When Bob views the shared cash ledger:
        - The date, credit amount (750.00), and running balance are shown.
        - The narration is redacted to '[Redacted]'.
        - The author is redacted to '[Redacted]'.
        - Direct link to entry_detail is suppressed.
        """
        response = self.client_bob.get(reverse("account_ledger", kwargs={"pk": self.shared_cash.pk}))
        self.assertEqual(response.status_code, 200)

        # Running balance and financial amount are exact
        self.assertContains(response, "750.00")

        # Private narration is NOT exposed to Bob
        self.assertNotContains(response, "Alice personal investment deposit")
        self.assertContains(response, "[Redacted]")

        # Entry detail link is suppressed
        detail_link = reverse("entry_detail", kwargs={"pk": self.mixed_entry.pk})
        self.assertNotContains(response, f'href="{detail_link}"')

    def test_full_visibility_on_shared_account_ledger_for_authorized_user(self):
        """Alice (who can see both accounts) sees full unredacted narration and entry link."""
        response = self.client_alice.get(reverse("account_ledger", kwargs={"pk": self.shared_cash.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice personal investment deposit")
        detail_link = reverse("entry_detail", kwargs={"pk": self.mixed_entry.pk})
        self.assertContains(response, f'href="{detail_link}"')


# ---------------------------------------------------------------------------
# A10 — Repeated/concurrent reversal yields one linked full reversal
# ---------------------------------------------------------------------------

class A10ConcurrentReversalRaceTests(TransactionTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_a10", password="pw", role="ADMIN")
        self.cash = make_account("CASH_10")
        self.bank = make_account("BANK_10")
        LedgerSettings.objects.get_or_create(pk=1)

    def tearDown(self):
        for conn in connections.all():
            conn.close()

    def test_concurrent_reversal_race_yields_one_reversal(self):
        """
        Two concurrent threads race to reverse the same original entry with different keys.
        Exactly one succeeds; the other raises ServiceError('already been reversed').
        """
        draft = create_draft(
            self.admin,
            "2026-04-02",
            "Original entry for race reversal",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("300.00"), "credit": Decimal("0.00")},
                {"account_id": self.bank.pk, "debit": Decimal("0.00"), "credit": Decimal("300.00")},
            ],
        )
        original = post_entry(self.admin, draft, 1, uuid.uuid4())

        key1, key2 = uuid.uuid4(), uuid.uuid4()
        successes = []
        errors = []

        def do_reverse(key):
            try:
                rev = reverse_entry(self.admin, original, "2026-04-03", "Race reversal", key)
                successes.append(rev)
            except ServiceError as e:
                errors.append(e)
            finally:
                for c in connections.all():
                    c.close()

        t1 = threading.Thread(target=do_reverse, args=(key1,))
        t2 = threading.Thread(target=do_reverse, args=(key2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly 1 reversal created
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("already been reversed", str(errors[0]).lower())

        original.refresh_from_db()
        self.assertTrue(hasattr(original, "reversal"))
        self.assertEqual(original.reversal.state, EntryState.POSTED)
        self.assertEqual(JournalEntry.objects.filter(reversal_of=original).count(), 1)

    def test_reversal_of_reversal_rejected(self):
        """A reversal entry cannot itself be reversed."""
        draft = create_draft(
            self.admin,
            "2026-04-02",
            "To reverse",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": Decimal("0.00")},
                {"account_id": self.bank.pk, "debit": Decimal("0.00"), "credit": Decimal("100.00")},
            ],
        )
        orig = post_entry(self.admin, draft, 1, uuid.uuid4())
        rev = reverse_entry(self.admin, orig, "2026-04-03", "Reversal 1", uuid.uuid4())

        # Attempting to reverse the reversal entry
        with self.assertRaises(ServiceError):
            reverse_entry(self.admin, rev, "2026-04-04", "Reversal of reversal", uuid.uuid4())


# ---------------------------------------------------------------------------
# A13 — Lock-date changes and posting serialize cleanly under policy
# ---------------------------------------------------------------------------

class A13LockDateSerializationTests(TransactionTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_a13", password="pw", role="ADMIN")
        self.cash = make_account("CASH_13")
        self.bank = make_account("BANK_13")
        LedgerSettings.objects.get_or_create(pk=1)

    def tearDown(self):
        for conn in connections.all():
            conn.close()

    def test_lock_date_lowering_requires_non_empty_reason(self):
        """Setting or lowering the lock date without a reason fails."""
        with self.assertRaises(ServiceError) as ctx:
            set_posting_lock_date(self.admin, "2026-03-31", "")
        self.assertIn("reason is required", str(ctx.exception).lower())

        with self.assertRaises(ServiceError) as ctx2:
            set_posting_lock_date(self.admin, "2026-03-31", "   ")
        self.assertIn("reason is required", str(ctx2.exception).lower())

    def test_lock_date_change_and_concurrent_post_serialize(self):
        """
        Thread 1 attempts to post an entry dated 2026-04-05.
        Thread 2 sets lock date through 2026-04-10.
        Both acquire LedgerSettings lock, so they execute sequentially.
        If Thread 2 runs first, Thread 1 fails with locked-period ServiceError.
        If Thread 1 runs first, both succeed. In all cases no deadlock or corrupted state.
        """
        draft = create_draft(
            self.admin,
            "2026-04-05",
            "Race against lock date change",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("250.00"), "credit": Decimal("0.00")},
                {"account_id": self.bank.pk, "debit": Decimal("0.00"), "credit": Decimal("250.00")},
            ],
        )

        outcome_post = []
        outcome_lock = []

        def do_post():
            try:
                r = post_entry(self.admin, draft, 1, uuid.uuid4())
                outcome_post.append("POSTED")
            except ServiceError as e:
                outcome_post.append(f"REJECTED: {e}")
            finally:
                for c in connections.all():
                    c.close()

        def do_lock():
            try:
                set_posting_lock_date(self.admin, "2026-04-10", "Quarter close lock")
                outcome_lock.append("LOCKED")
            except Exception as e:
                outcome_lock.append(f"LOCK_ERROR: {e}")
            finally:
                for c in connections.all():
                    c.close()

        t1 = threading.Thread(target=do_post)
        t2 = threading.Thread(target=do_lock)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn("LOCKED", outcome_lock)
        self.assertEqual(len(outcome_post), 1)
        # Outcome is either successfully posted (if post won the lock) or cleanly rejected (if lock won)
        post_res = outcome_post[0]
        self.assertTrue(post_res == "POSTED" or "lock date" in post_res.lower(), f"Unexpected outcome: {post_res}")


# ---------------------------------------------------------------------------
# A20 — Coordinated permission/actor-state changes at posting boundary
# ---------------------------------------------------------------------------

class A20PostingBoundaryPermissionTests(TransactionTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_a20", password="pw", role="ADMIN")
        self.member = User.objects.create_user(username="member_a20", password="pw", role="MEMBER")
        self.cash = make_account("CASH_20", visibility=Visibility.SHARED)
        self.bank = make_account("BANK_20", visibility=Visibility.SHARED)
        LedgerSettings.objects.get_or_create(pk=1)

        # Grant member permissions on cash and bank
        AccountGrant.objects.create(account=self.cash, user=self.member, can_view=True, can_post=True)
        AccountGrant.objects.create(account=self.bank, user=self.member, can_view=True, can_post=True)

    def tearDown(self):
        for conn in connections.all():
            conn.close()

    def test_actor_deactivation_rejected_at_posting_boundary(self):
        """
        If a user is deactivated concurrently after draft creation,
        the reload of actor inside the coordinated transaction rejects the post.
        """
        draft = create_draft(
            self.member,
            "2026-04-06",
            "Draft before deactivation",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": Decimal("0.00")},
                {"account_id": self.bank.pk, "debit": Decimal("0.00"), "credit": Decimal("100.00")},
            ],
        )

        # Deactivate user in database
        User.objects.filter(pk=self.member.pk).update(is_active=False)

        # Attempt to post using the existing in-memory member instance
        with self.assertRaises(AuthorizationError) as ctx:
            post_entry(self.member, draft, 1, uuid.uuid4())
        self.assertIn("inactive", str(ctx.exception).lower())
        self.assertEqual(JournalEntry.objects.filter(state=EntryState.POSTED).count(), 0)

    def test_grant_revocation_rejected_at_posting_boundary(self):
        """
        If a user's posting grant is revoked concurrently,
        permission checks inside the coordinated lock reject the post.
        """
        draft = create_draft(
            self.member,
            "2026-04-06",
            "Draft before grant revocation",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("150.00"), "credit": Decimal("0.00")},
                {"account_id": self.bank.pk, "debit": Decimal("0.00"), "credit": Decimal("150.00")},
            ],
        )

        # Revoke posting grant on bank account
        AccountGrant.objects.filter(account=self.bank, user=self.member).update(can_post=False)

        with self.assertRaises(AuthorizationError) as ctx:
            post_entry(self.member, draft, 1, uuid.uuid4())
        self.assertIn("posting rights", str(ctx.exception).lower())
        self.assertEqual(JournalEntry.objects.filter(state=EntryState.POSTED).count(), 0)

    def test_settings_lock_date_renders_activity_records_cleanly(self):
        """
        Regression guardrail: settings_lock_date view must order ActivityRecord
        by -created_at without FieldError.
        """
        from django.test import Client
        from apps.operations.models import ActivityRecord
        ActivityRecord.objects.create(
            actor=self.admin,
            action="SET_LOCK_DATE",
            object_type="LedgerSettings",
            object_id="1",
            metadata={"locked_through": "2026-03-31", "reason": "Monthly close test"},
        )
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("settings_lock_date"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monthly close test")

    def test_visible_entries_query_scoping(self):
        """
        Regression guardrail: visible_entries scopes queries at the DB level,
        hiding entries that touch accounts invisible to member.
        """
        from apps.accounting.policies import visible_entries
        savings = make_account("SAVINGS_20", visibility=Visibility.PERSONAL, owner=self.admin)
        draft = create_draft(
            self.admin,
            "2026-04-06",
            "Secret admin entry",
            EntryKind.JOURNAL,
            [
                {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": Decimal("0.00")},
                {"account_id": savings.pk, "debit": Decimal("0.00"), "credit": Decimal("100.00")},
            ],
        )
        # Visible to admin
        self.assertTrue(visible_entries(self.admin).filter(pk=draft.pk).exists())
        # Invisible to member at DB level
        self.assertFalse(visible_entries(self.member).filter(pk=draft.pk).exists())


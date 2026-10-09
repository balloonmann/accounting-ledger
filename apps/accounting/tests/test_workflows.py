import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
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
from apps.accounting.services import (
    AuthorizationError,
    ConflictError,
    ServiceError,
    StaleVersionError,
    create_account,
    create_draft,
    deactivate_account,
    delete_account,
    delete_draft,
    post_entry,
    reverse_entry,
    update_account,
    update_draft,
)

User = get_user_model()


class WorkflowBaseTestCase(TestCase):
    def setUp(self):
        self.settings, _ = LedgerSettings.objects.get_or_create(
            id=1,
            defaults={
                "name": "Household Ledger Test",
                "currency": "INR",
                "timezone_name": "Asia/Kolkata",
                "fiscal_start_month": 4,
                "fiscal_start_day": 1,
            },
        )

        self.admin = User.objects.create_user(
            username="admin_user",
            password="adminpassword123",
            role=User.Role.ADMIN,
        )

        self.member = User.objects.create_user(
            username="member_user",
            password="memberpassword123",
            role=User.Role.MEMBER,
        )

        self.other_member = User.objects.create_user(
            username="other_user",
            password="otherpassword123",
            role=User.Role.MEMBER,
        )

        # Asset accounts
        self.cash = create_account(
            self.admin,
            code="1010",
            name="Cash Account",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.CASH,
            normal_side=Side.DEBIT,
            visibility=Visibility.SHARED,
        )

        self.bank = create_account(
            self.admin,
            code="1020",
            name="Bank Account",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.BANK,
            normal_side=Side.DEBIT,
            visibility=Visibility.SHARED,
        )

        # Equity
        self.opening_equity = create_account(
            self.admin,
            code="3010",
            name="Opening Equity",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.EQUITY,
            purpose=Purpose.OPENING_EQUITY,
            normal_side=Side.CREDIT,
            visibility=Visibility.SHARED,
        )
        self.settings.opening_equity = self.opening_equity
        self.settings.save()

        # Income & Expense
        self.salary = create_account(
            self.admin,
            code="4010",
            name="Salary Income",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.INCOME,
            purpose=Purpose.GENERAL,
            normal_side=Side.CREDIT,
            visibility=Visibility.SHARED,
        )

        self.groceries = create_account(
            self.admin,
            code="5010",
            name="Groceries Expense",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            visibility=Visibility.SHARED,
        )

        # Private account for other_member
        self.private_acc = create_account(
            self.admin,
            code="1099",
            name="Private Stash",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.CASH,
            normal_side=Side.DEBIT,
            visibility=Visibility.PERSONAL,
            owner=self.other_member,
        )

        # Grants for member
        for acc in [self.cash, self.bank, self.salary, self.groceries]:
            AccountGrant.objects.create(
                user=self.member,
                account=acc,
                can_view=True,
                can_post=True,
            )

        self.client_admin = Client()
        self.client_admin.login(username="admin_user", password="adminpassword123")

        self.client_member = Client()
        self.client_member.login(username="member_user", password="memberpassword123")


class AccountManagementWorkflowTests(WorkflowBaseTestCase):
    def test_admin_can_create_and_update_unused_account(self):
        acc = create_account(
            self.admin,
            code="5020",
            name="Electricity",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            visibility=Visibility.SHARED,
        )
        self.assertEqual(acc.name, "Electricity")

        updated = update_account(self.admin, acc, name="Electricity & Utilities", code="5025")
        self.assertEqual(updated.name, "Electricity & Utilities")
        self.assertEqual(updated.code, "5025")

    def test_non_admin_cannot_create_or_update_accounts(self):
        with self.assertRaises(AuthorizationError):
            create_account(
                self.member,
                code="5099",
                name="Disallowed",
                classical_type=ClassicalType.NOMINAL,
                reporting_class=ReportingClass.EXPENSE,
                purpose=Purpose.GENERAL,
                normal_side=Side.DEBIT,
                visibility=Visibility.SHARED,
            )

        with self.assertRaises(AuthorizationError):
            update_account(self.member, self.groceries, name="Hacked Name")

    def test_frozen_fields_on_used_accounts_d04(self):
        # Post a transaction using groceries
        draft = create_draft(
            self.admin,
            "2026-04-01",
            "Bought food",
            EntryKind.EXPENSE,
            [
                {"account_id": self.groceries.pk, "debit": Decimal("100.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("100.00")},
            ],
        )
        post_entry(self.admin, draft, draft.version, uuid.uuid4())

        # Attempting to change frozen field (reporting_class, classical_type, normal_side, purpose) raises ServiceError
        with self.assertRaises(ServiceError):
            update_account(self.admin, self.groceries, reporting_class=ReportingClass.ASSET)

        with self.assertRaises(ServiceError):
            update_account(self.admin, self.groceries, normal_side=Side.CREDIT)

        # Changing harmless label/name succeeds
        updated = update_account(self.admin, self.groceries, name="Supermarket Groceries")
        self.assertEqual(updated.name, "Supermarket Groceries")

    def test_deactivate_account_and_configured_protection(self):
        # Cannot deactivate configured opening equity
        with self.assertRaises(ServiceError):
            deactivate_account(self.admin, self.opening_equity)

        # Can deactivate active unused account
        unused = create_account(
            self.admin,
            code="5090",
            name="Temporary Account",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            visibility=Visibility.SHARED,
        )
        deactivated = deactivate_account(self.admin, unused)
        self.assertFalse(deactivated.is_active)

        # Cannot deactivate already inactive account
        with self.assertRaises(ServiceError):
            deactivate_account(self.admin, deactivated)

    def test_delete_account_protections_d08(self):
        # Cannot delete configured opening equity
        with self.assertRaises(ServiceError):
            delete_account(self.admin, self.opening_equity)

        # Cannot delete account with lines
        draft = create_draft(
            self.admin,
            "2026-04-01",
            "Initial",
            EntryKind.EXPENSE,
            [
                {"account_id": self.groceries.pk, "debit": Decimal("50.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("50.00")},
            ],
        )
        post_entry(self.admin, draft, draft.version, uuid.uuid4())

        with self.assertRaises(ServiceError):
            delete_account(self.admin, self.groceries)

        # Can delete unused account
        unused = create_account(
            self.admin,
            code="5088",
            name="To Delete",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            visibility=Visibility.SHARED,
        )
        delete_account(self.admin, unused)
        self.assertFalse(Account.objects.filter(code="5088").exists())


class EntryWorkflowViewTests(WorkflowBaseTestCase):
    def test_expense_workflow_post_and_draft(self):
        # 1. Post expense immediately
        key = uuid.uuid4()
        response = self.client_member.post(reverse("entry_expense"), {
            "date": "2026-04-10",
            "amount": "250.00",
            "source_account": str(self.cash.pk),
            "expense_account": str(self.groceries.pk),
            "narration": "Snacks at bakery",
            "idempotency_key": str(key),
            "action": "post",
        })
        self.assertEqual(response.status_code, 302)

        posted = JournalEntry.objects.filter(narration="Snacks at bakery").first()
        self.assertIsNotNone(posted)
        self.assertEqual(posted.state, EntryState.POSTED)
        self.assertIsNotNone(posted.posting_number)
        self.assertEqual(posted.lines.count(), 2)

        # 2. Save expense as draft
        response = self.client_member.post(reverse("entry_expense"), {
            "date": "2026-04-11",
            "amount": "300.00",
            "source_account": str(self.cash.pk),
            "expense_account": str(self.groceries.pk),
            "narration": "Planned bakery run",
            "idempotency_key": str(uuid.uuid4()),
            "action": "draft",
        })
        self.assertEqual(response.status_code, 302)

        draft = JournalEntry.objects.filter(narration="Planned bakery run").first()
        self.assertIsNotNone(draft)
        self.assertEqual(draft.state, EntryState.DRAFT)
        self.assertIsNone(draft.posting_number)

    def test_income_workflow(self):
        key = uuid.uuid4()
        response = self.client_member.post(reverse("entry_income"), {
            "date": "2026-04-02",
            "amount": "15000.00",
            "destination_account": str(self.bank.pk),
            "income_account": str(self.salary.pk),
            "narration": "Contract payout",
            "idempotency_key": str(key),
            "action": "post",
        })
        self.assertEqual(response.status_code, 302)

        entry = JournalEntry.objects.filter(narration="Contract payout").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.state, EntryState.POSTED)
        dest_line = entry.lines.get(account=self.bank)
        self.assertEqual(dest_line.debit, Decimal("15000.00"))

    def test_transfer_workflow(self):
        # Valid transfer
        response = self.client_member.post(reverse("entry_transfer"), {
            "date": "2026-04-03",
            "amount": "1000.00",
            "from_account": str(self.cash.pk),
            "to_account": str(self.bank.pk),
            "narration": "Cash deposit",
            "idempotency_key": str(uuid.uuid4()),
            "action": "post",
        })
        self.assertEqual(response.status_code, 302)

        # Invalid transfer (same source and destination)
        response = self.client_member.post(reverse("entry_transfer"), {
            "date": "2026-04-03",
            "amount": "1000.00",
            "from_account": str(self.cash.pk),
            "to_account": str(self.cash.pk),
            "narration": "Invalid transfer",
            "idempotency_key": str(uuid.uuid4()),
            "action": "post",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transfer source and destination must be different accounts.")

    def test_unauthorized_account_rejected_a08(self):
        # Member attempts to post using private_acc (which belongs to other_member)
        response = self.client_member.post(reverse("entry_expense"), {
            "date": "2026-04-05",
            "amount": "100.00",
            "source_account": str(self.private_acc.pk),  # Unauthorized!
            "expense_account": str(self.groceries.pk),
            "narration": "Hacking private stash",
            "idempotency_key": str(uuid.uuid4()),
            "action": "post",
        })
        # Rejected by form validation (account not in postable queryset)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JournalEntry.objects.filter(narration="Hacking private stash").exists())

    def test_full_journal_workflow_and_balancing_check(self):
        # 1. Balanced multi-line submission
        response = self.client_member.post(reverse("entry_journal"), {
            "date": "2026-04-07",
            "narration": "Split purchase",
            "idempotency_key": str(uuid.uuid4()),
            "action": "post",
            "line_account[]": [str(self.groceries.pk), str(self.cash.pk), str(self.bank.pk)],
            "line_debit[]": ["500.00", "0.00", "0.00"],
            "line_credit[]": ["0.00", "200.00", "300.00"],
        })
        self.assertEqual(response.status_code, 302)

        entry = JournalEntry.objects.filter(narration="Split purchase").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.state, EntryState.POSTED)
        self.assertEqual(entry.lines.count(), 3)

        # 2. Unbalanced submission is rejected and preserves user lines
        response = self.client_member.post(reverse("entry_journal"), {
            "date": "2026-04-07",
            "narration": "Unbalanced purchase",
            "idempotency_key": str(uuid.uuid4()),
            "action": "post",
            "line_account[]": [str(self.groceries.pk), str(self.cash.pk)],
            "line_debit[]": ["500.00", "0.00"],
            "line_credit[]": ["0.00", "400.00"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Journal is not balanced")
        self.assertFalse(JournalEntry.objects.filter(narration="Unbalanced purchase").exists())

    def test_opening_balance_admin_only(self):
        # Non-admin forbidden
        response = self.client_member.post(reverse("entry_opening"), {
            "date": "2026-04-01",
            "amount": "1000.00",
            "account": str(self.cash.pk),
            "side": Side.DEBIT,
            "offset_account": str(self.opening_equity.pk),
            "narration": "Member attempting opening balance",
            "idempotency_key": str(uuid.uuid4()),
            "action": "post",
        })
        self.assertEqual(response.status_code, 403)

        # Admin succeeds
        response = self.client_admin.post(reverse("entry_opening"), {
            "date": "2026-04-01",
            "amount": "1000.00",
            "account": str(self.cash.pk),
            "side": Side.DEBIT,
            "offset_account": str(self.opening_equity.pk),
            "narration": "Admin initial opening",
            "idempotency_key": str(uuid.uuid4()),
            "action": "post",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(JournalEntry.objects.filter(narration="Admin initial opening").exists())


class DraftConcurrencyAndLifecycleTests(WorkflowBaseTestCase):
    def test_draft_concurrency_conflict_a07(self):
        draft = create_draft(
            self.member,
            "2026-04-01",
            "Draft to edit",
            EntryKind.JOURNAL,
            [
                {"account_id": self.groceries.pk, "debit": Decimal("100.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("100.00")},
            ],
        )
        self.assertEqual(draft.version, 1)

        # User 1 updates the draft via service
        update_draft(
            self.member,
            draft,
            submitted_version=1,
            date="2026-04-01",
            narration="Updated by session 1",
            kind=EntryKind.JOURNAL,
            line_specs=[
                {"account_id": self.groceries.pk, "debit": Decimal("150.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("150.00")},
            ],
        )
        draft.refresh_from_db()
        self.assertEqual(draft.version, 2)

        # User 2 tries to edit with stale version 1 via web form
        response = self.client_member.post(reverse("draft_edit", kwargs={"pk": draft.pk}), {
            "date": "2026-04-01",
            "narration": "Conflict edit by session 2",
            "version": 1,  # Stale!
            "idempotency_key": str(uuid.uuid4()),
            "action": "save",
            "line_account[]": [str(self.groceries.pk), str(self.cash.pk)],
            "line_debit[]": ["200.00", "0.00"],
            "line_credit[]": ["0.00", "200.00"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This draft was modified by another session")

    def test_draft_delete_and_post_views(self):
        draft = create_draft(
            self.member,
            "2026-04-01",
            "To post or delete",
            EntryKind.JOURNAL,
            [
                {"account_id": self.groceries.pk, "debit": Decimal("50.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("50.00")},
            ],
        )

        # Post draft view
        response = self.client_member.post(reverse("draft_post", kwargs={"pk": draft.pk}))
        self.assertEqual(response.status_code, 302)

        draft.refresh_from_db()
        self.assertEqual(draft.state, EntryState.POSTED)
        self.assertIsNotNone(draft.posting_number)

        # Create another draft to delete
        draft2 = create_draft(
            self.member,
            "2026-04-02",
            "To delete",
            EntryKind.JOURNAL,
            [
                {"account_id": self.groceries.pk, "debit": Decimal("50.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("50.00")},
            ],
        )
        response = self.client_member.post(reverse("draft_delete", kwargs={"pk": draft2.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(JournalEntry.objects.filter(pk=draft2.pk).exists())


class EntryDetailAndReversalTests(WorkflowBaseTestCase):
    def test_entry_detail_privacy_redaction_rule(self):
        # Entry containing private account of other_member
        draft = create_draft(
            self.admin,
            "2026-04-01",
            "Private transaction",
            EntryKind.JOURNAL,
            [
                {"account_id": self.private_acc.pk, "debit": Decimal("500.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("500.00")},
            ],
        )
        posted = post_entry(self.admin, draft, draft.version, uuid.uuid4())

        # member_user does not have permission on private_acc -> entry detail returns 403 Forbidden
        response = self.client_member.get(reverse("entry_detail", kwargs={"pk": posted.pk}))
        self.assertEqual(response.status_code, 403)

        # admin_user can view full detail
        response = self.client_admin.get(reverse("entry_detail", kwargs={"pk": posted.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Posting #")

    def test_reversal_workflow_and_replacement_link(self):
        # 1. Post original entry
        draft = create_draft(
            self.member,
            "2026-04-01",
            "Groceries expense",
            EntryKind.EXPENSE,
            [
                {"account_id": self.groceries.pk, "debit": Decimal("400.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("400.00")},
            ],
        )
        posted = post_entry(self.member, draft, draft.version, uuid.uuid4())

        # 2. Reverse entry via view
        response = self.client_member.post(reverse("entry_reverse", kwargs={"pk": posted.pk}), {
            "reversal_date": "2026-04-02",
            "narration": "Reversing grocery charge",
            "idempotency_key": str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 302)

        posted.refresh_from_db()
        self.assertTrue(hasattr(posted, "reversal"))
        reversal = posted.reversal
        self.assertEqual(reversal.state, EntryState.POSTED)
        self.assertEqual(reversal.reversal_of, posted)

        # Lines in reversal are swapped
        rev_groc = reversal.lines.get(account=self.groceries)
        self.assertEqual(rev_groc.credit, Decimal("400.00"))
        rev_cash = reversal.lines.get(account=self.cash)
        self.assertEqual(rev_cash.debit, Decimal("400.00"))

        # 3. Create replacement draft via replace view
        response = self.client_member.get(reverse("entry_replace", kwargs={"pk": posted.pk}))
        self.assertEqual(response.status_code, 302)

        repl_draft = JournalEntry.objects.filter(replacement_of=posted).first()
        self.assertIsNotNone(repl_draft)
        self.assertEqual(repl_draft.state, EntryState.DRAFT)


class GoldenDatasetAcceptanceTest(WorkflowBaseTestCase):
    def test_bible_section_11_golden_dataset_balances(self):
        from django.core.management import call_command

        # Clear existing entries and run seed_demo command
        call_command("seed_demo", "--reset", "--password", "SecretTestPass!99")

        # Fetch accounts
        cash = Account.objects.get(code="1010")
        bank = Account.objects.get(code="1020")
        opening_eq = Account.objects.get(code="3010")
        salary = Account.objects.get(code="4010")
        groceries = Account.objects.get(code="5010")

        def balance(acc):
            lines = JournalLine.objects.filter(entry__state="POSTED", account=acc)
            debits = sum((l.debit for l in lines), Decimal("0.00"))
            credits = sum((l.credit for l in lines), Decimal("0.00"))
            return debits, credits

        cash_dr, cash_cr = balance(cash)
        bank_dr, bank_cr = balance(bank)
        groc_dr, groc_cr = balance(groceries)
        sal_dr, sal_cr = balance(salary)
        eq_dr, eq_cr = balance(opening_eq)

        # Bible §11 exact expectations:
        # Cash: Dr ₹7,550
        self.assertEqual(cash_dr - cash_cr, Decimal("7550.00"))
        # Bank: Dr ₹22,000
        self.assertEqual(bank_dr - bank_cr, Decimal("22000.00"))
        # Groceries: Dr ₹450
        self.assertEqual(groc_dr - groc_cr, Decimal("450.00"))
        # Salary Income: Cr ₹20,000
        self.assertEqual(sal_cr - sal_dr, Decimal("20000.00"))
        # Opening Equity: Cr ₹10,000
        self.assertEqual(eq_cr - eq_dr, Decimal("10000.00"))

        # Surplus: Income less expense = 20,000 - 450 = 19,550
        surplus = (sal_cr - sal_dr) - (groc_dr - groc_cr)
        self.assertEqual(surplus, Decimal("19550.00"))

        # Cash and bank combined: 7,550 + 22,000 = 29,550
        liquid = (cash_dr - cash_cr) + (bank_dr - bank_cr)
        self.assertEqual(liquid, Decimal("29550.00"))

        # Verify that unposted drafts do NOT affect balances
        draft_count = JournalEntry.objects.filter(state=EntryState.DRAFT).count()
        self.assertGreaterEqual(draft_count, 1)

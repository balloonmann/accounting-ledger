"""
Milestone 4 Acceptance Tests: Financial Reports, Ledgers, and CSV Export.
Covers:
  - A14: Golden dataset produces exact expected balances across Trial Balance & Income/Expenditure.
  - A15: Date-filtered ledger has correct opening and running balances.
  - A09 (Complete): Mixed-visibility redaction holds across screen and CSV export.
  - Formula injection neutralization in CSV exports.
  - Administrative authorization boundaries on reports.
"""
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounting.choices import ClassicalType, EntryKind, EntryState, Purpose, ReportingClass, Side, Visibility
from apps.accounting.models import Account, AccountGrant, JournalEntry, JournalLine, LedgerSettings
from apps.accounting.services import create_draft, post_entry
from apps.reporting.reports import (
    current_fiscal_year_start,
    export_ledger_csv,
    get_account_ledger_data,
    get_income_expenditure_data,
    get_trial_balance_data,
    sanitize_csv_cell,
)

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


class FinancialReportsAndExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Run seed_demo to establish the Bible §11 Golden Dataset
        call_command("seed_demo", reset=True, stdout=None)

        cls.admin = User.objects.get(username="admin_demo")
        cls.member = User.objects.get(username="member_demo")

        cls.cash = Account.objects.get(code="1010")
        cls.bank = Account.objects.get(code="1020")
        cls.groceries = Account.objects.get(code="5010")
        cls.salary = Account.objects.get(code="4010")
        cls.opening_equity = Account.objects.get(code="3000")

    def setUp(self):
        self.client_admin = Client()
        self.client_admin.force_login(self.admin)
        self.client_member = Client()
        self.client_member.force_login(self.member)

    # -----------------------------------------------------------------------
    # A14 — Golden Dataset expected results across reports
    # -----------------------------------------------------------------------

    def test_golden_dataset_trial_balance_a14(self):
        """
        Trial balance over Golden Dataset:
          - Cash Dr 7,550.00
          - Bank Dr 22,000.00
          - Groceries Expense Dr 450.00
          - Salary Income Cr 20,000.00
          - Opening Equity Cr 10,000.00
          - Grand totals: Dr 30,000.00 and Cr 30,000.00 (Balanced!)
        """
        tb = get_trial_balance_data()
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["grand_total_debit"], Decimal("30000.00"))
        self.assertEqual(tb["grand_total_credit"], Decimal("30000.00"))

        # Check web view response
        response = self.client_admin.get(reverse("trial_balance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "30000.00")
        self.assertContains(response, "Books Balanced")

    def test_golden_dataset_income_expenditure_a14(self):
        """
        Income & Expenditure over Golden Dataset:
          - Salary Income: 20,000.00
          - Groceries Expense: 450.00
          - Net Surplus: 19,550.00
        """
        ie = get_income_expenditure_data()
        self.assertEqual(ie["total_income"], Decimal("20000.00"))
        self.assertEqual(ie["total_expense"], Decimal("450.00"))
        self.assertEqual(ie["net_surplus"], Decimal("19550.00"))
        self.assertTrue(ie["is_surplus"])

        # Check web view response
        response = self.client_admin.get(reverse("income_expenditure"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "20000.00")
        self.assertContains(response, "450.00")
        self.assertContains(response, "19550.00")
        self.assertContains(response, "Net Surplus")

    # -----------------------------------------------------------------------
    # A15 — Date-filtered ledger opening and running balances
    # -----------------------------------------------------------------------

    def test_date_filtered_ledger_opening_and_running_balances_a15(self):
        """
        Account ledger filtered after initial transactions:
        Cash transactions in Golden Dataset:
          Event 1 (2026-04-01): Opening Cash Dr 10,000.00
          Event 3 (2026-04-03): Groceries Cr 500.00
          Event 4 (2026-04-04): Transfer to Bank Cr 2,000.00
          Event 5 (2026-04-05): Reversal of groceries Dr 500.00
          Event 6 (2026-04-05): Corrected groceries Cr 450.00
        If filtering from 2026-04-04:
          Opening balance (before 2026-04-04) = 10,000 - 500 = 9,500.00
          Period debits/credits on or after 2026-04-04:
            - Transfer: Cr 2,000 (running: 7,500.00)
            - Reversal: Dr 500   (running: 8,000.00)
            - Corrected: Cr 450  (running: 7,550.00)
          Closing balance = 7,550.00
        """
        from datetime import date
        ledger = get_account_ledger_data(
            self.admin,
            self.cash,
            start_date=date(2026, 4, 4),
            end_date=date(2026, 4, 6),
        )

        self.assertEqual(ledger["opening_balance"], Decimal("9500.00"))
        self.assertEqual(ledger["closing_balance"], Decimal("7550.00"))
        self.assertEqual(ledger["total_debit"], Decimal("500.00"))
        self.assertEqual(ledger["total_credit"], Decimal("2450.00"))

        # Verify HTML view renders the opening balance and running balances correctly
        response = self.client_admin.get(
            reverse("account_ledger", kwargs={"pk": self.cash.pk}) + "?start_date=2026-04-04&end_date=2026-04-06"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "9500.00")
        self.assertContains(response, "7550.00")

    # -----------------------------------------------------------------------
    # A09 & CSV Export — Mixed-visibility redaction and formula protection
    # -----------------------------------------------------------------------

    def test_mixed_visibility_redaction_holds_in_csv_export_a09(self):
        """
        Mixed-visibility journal:
        Alice deposits INR 600 from shared Cash into her private Investment account.
        When Member (who cannot view Alice's private account) downloads Cash ledger CSV:
          - Narration is '[Redacted]'
          - Author is '[Redacted]'
          - Financial debit/credit amounts and running balance are intact
        """
        alice = User.objects.create_user(username="alice_m4", password="pw", role="MEMBER")
        pvt_acc = make_account("ALICE_PVT_M4", visibility=Visibility.PERSONAL, owner=alice)

        # Grant Alice post rights on cash
        AccountGrant.objects.create(account=self.cash, user=alice, can_view=True, can_post=True)

        draft = create_draft(
            alice,
            "2026-04-07",
            "Alice secret private deposit",
            EntryKind.JOURNAL,
            [
                {"account_id": pvt_acc.pk, "debit": Decimal("600.00"), "credit": Decimal("0.00")},
                {"account_id": self.cash.pk, "debit": Decimal("0.00"), "credit": Decimal("600.00")},
            ],
        )
        post_entry(alice, draft, 1, uuid.uuid4())

        # Member requests CSV export
        response = self.client_member.get(reverse("account_ledger", kwargs={"pk": self.cash.pk}) + "?export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        csv_text = response.content.decode("utf-8")

        # Must NOT expose private narration or author to unauthorized member
        self.assertNotIn("Alice secret private deposit", csv_text)
        self.assertIn("[Redacted]", csv_text)
        # Financial amounts are exact
        self.assertIn("600.00", csv_text)

    def test_formula_injection_neutralization_in_csv(self):
        """
        Free-text cells starting with '=', '+', '-', '@', '\t', '\r'
        must be prefixed with a single quote (') to prevent CSV formula injection.
        """
        malicious_inputs = [
            "=SUM(A1:A10)",
            "+cmd|' /C calc'!A0",
            "-2+3*[1]!A1",
            "@IMPORTXML('http://evil.com')",
            "\tTAB_INJECT",
        ]

        for payload in malicious_inputs:
            sanitized = sanitize_csv_cell(payload)
            self.assertTrue(sanitized.startswith("'"), f"Payload {payload} was not sanitized: {sanitized}")

        # Normal text should NOT be modified
        self.assertEqual(sanitize_csv_cell("Normal expense"), "Normal expense")
        self.assertEqual(sanitize_csv_cell("Grocery purchase"), "Grocery purchase")

    # -----------------------------------------------------------------------
    # Authorization Boundaries
    # -----------------------------------------------------------------------

    def test_non_admin_cannot_access_reports_or_export(self):
        """Members cannot access Trial Balance or Income/Expenditure screens or CSVs."""
        # Trial Balance HTML
        r1 = self.client_member.get(reverse("trial_balance"))
        self.assertEqual(r1.status_code, 403)

        # Trial Balance CSV
        r2 = self.client_member.get(reverse("trial_balance") + "?export=csv")
        self.assertEqual(r2.status_code, 403)

        # Income & Expenditure HTML
        r3 = self.client_member.get(reverse("income_expenditure"))
        self.assertEqual(r3.status_code, 403)

        # Income & Expenditure CSV
        r4 = self.client_member.get(reverse("income_expenditure") + "?export=csv")
        self.assertEqual(r4.status_code, 403)

    def test_admin_csv_exports_succeed(self):
        """Admin can successfully download CSV exports for Trial Balance and Income/Expenditure."""
        r_tb = self.client_admin.get(reverse("trial_balance") + "?export=csv")
        self.assertEqual(r_tb.status_code, 200)
        self.assertEqual(r_tb["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Trial Balance", r_tb.content.decode("utf-8"))
        self.assertIn("30000.00", r_tb.content.decode("utf-8"))

        r_ie = self.client_admin.get(reverse("income_expenditure") + "?export=csv")
        self.assertEqual(r_ie.status_code, 200)
        self.assertEqual(r_ie["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Income & Expenditure", r_ie.content.decode("utf-8"))
        self.assertIn("19550.00", r_ie.content.decode("utf-8"))

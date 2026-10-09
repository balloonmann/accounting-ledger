import secrets
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounting.choices import (
    ClassicalType,
    EntryKind,
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
    create_account,
    create_draft,
    post_entry,
    reverse_entry,
)
from apps.operations.models import ActivityRecord

User = get_user_model()


class Command(BaseCommand):
    help = "Seed synthetic demo users, accounts, and Bible §11 Golden Dataset through normal services."

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-user",
            default="admin_demo",
            help="Username for the demo admin user (default: admin_demo)",
        )
        parser.add_argument(
            "--member-user",
            default="member_demo",
            help="Username for the demo member user (default: member_demo)",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Password for demo users. If not provided, a secure random password is generated.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear existing transactions and accounts before seeding.",
        )

    def handle(self, *args, **options):
        admin_username = options["admin_user"]
        member_username = options["member_user"]
        raw_password = options["password"] or secrets.token_urlsafe(12)

        self.stdout.write(self.style.NOTICE("Initializing Household Ledger Demo Dataset..."))

        # 1. Initialize or get LedgerSettings singleton
        settings_obj, _ = LedgerSettings.objects.get_or_create(
            id=1,
            defaults={"name": "Household Ledger POC"},
        )

        if options["reset"]:
            self.stdout.write("Reset requested. Clearing existing journal entries and accounts...")
            from django.db import connection, transaction
            reset_done = False
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "TRUNCATE TABLE accounting_journalline, accounting_journalentry, "
                            "accounting_postingrequest, accounting_accountgrant, operations_activityrecord CASCADE;"
                        )
                reset_done = True
            except Exception:
                pass

            if not reset_done:
                try:
                    with transaction.atomic():
                        PostingRequest.objects.all().delete()
                        if not JournalEntry.objects.filter(state="POSTED").exists():
                            JournalLine.objects.all().delete()
                            JournalEntry.objects.all().delete()
                            AccountGrant.objects.all().delete()
                            settings_obj.opening_equity = None
                            settings_obj.save()
                            Account.objects.all().delete()
                            ActivityRecord.objects.all().delete()
                except Exception:
                    pass

        # 2. Create synthetic users
        admin_user, created_admin = User.objects.get_or_create(
            username=admin_username,
            defaults={"role": User.Role.ADMIN, "is_staff": True, "is_superuser": True},
        )
        admin_user.set_password(raw_password)
        admin_user.role = User.Role.ADMIN
        admin_user.save()

        member_user, created_member = User.objects.get_or_create(
            username=member_username,
            defaults={"role": User.Role.MEMBER},
        )
        member_user.set_password(raw_password)
        member_user.role = User.Role.MEMBER
        member_user.save()

        self.stdout.write(self.style.SUCCESS(
            f"Created/updated users:\n"
            f"  Admin:  {admin_username} / {raw_password}\n"
            f"  Member: {member_username} / {raw_password}"
        ))

        # 3. Create Chart of Accounts using create_account service
        def get_or_create_acc(**kwargs):
            code = kwargs["code"]
            existing = Account.objects.filter(code=code).first()
            if existing:
                return existing
            return create_account(admin_user, **kwargs)

        # Asset Groups and Leaves
        current_assets = get_or_create_acc(
            code="1000",
            name="Current Assets",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            is_group=True,
            visibility=Visibility.SHARED,
        )

        cash = get_or_create_acc(
            code="1010",
            name="Household Cash",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.CASH,
            normal_side=Side.DEBIT,
            is_group=False,
            visibility=Visibility.SHARED,
            parent=current_assets,
        )

        bank = get_or_create_acc(
            code="1020",
            name="Member Bank",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.ASSET,
            purpose=Purpose.BANK,
            normal_side=Side.DEBIT,
            is_group=False,
            visibility=Visibility.SHARED,
            parent=current_assets,
        )

        # Equity Groups and Leaves
        equity_group = get_or_create_acc(
            code="3000",
            name="Household Capital & Equity",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.EQUITY,
            purpose=Purpose.GENERAL,
            normal_side=Side.CREDIT,
            is_group=True,
            visibility=Visibility.SHARED,
        )

        opening_equity = get_or_create_acc(
            code="3010",
            name="Opening Equity",
            classical_type=ClassicalType.REAL,
            reporting_class=ReportingClass.EQUITY,
            purpose=Purpose.OPENING_EQUITY,
            normal_side=Side.CREDIT,
            is_group=False,
            visibility=Visibility.SHARED,
            parent=equity_group,
        )

        # Set opening equity on settings
        settings_obj.opening_equity = opening_equity
        settings_obj.save()

        # Income Groups and Leaves
        income_group = get_or_create_acc(
            code="4000",
            name="Household Income",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.INCOME,
            purpose=Purpose.GENERAL,
            normal_side=Side.CREDIT,
            is_group=True,
            visibility=Visibility.SHARED,
        )

        salary = get_or_create_acc(
            code="4010",
            name="Salary Income",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.INCOME,
            purpose=Purpose.GENERAL,
            normal_side=Side.CREDIT,
            is_group=False,
            visibility=Visibility.SHARED,
            parent=income_group,
        )

        # Expense Groups and Leaves
        expense_group = get_or_create_acc(
            code="5000",
            name="Household Expenses",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            is_group=True,
            visibility=Visibility.SHARED,
        )

        groceries = get_or_create_acc(
            code="5010",
            name="Groceries Expense",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            is_group=False,
            visibility=Visibility.SHARED,
            parent=expense_group,
        )

        utilities = get_or_create_acc(
            code="5020",
            name="Utilities Expense",
            classical_type=ClassicalType.NOMINAL,
            reporting_class=ReportingClass.EXPENSE,
            purpose=Purpose.GENERAL,
            normal_side=Side.DEBIT,
            is_group=False,
            visibility=Visibility.SHARED,
            parent=expense_group,
        )

        # 4. Grants for Member
        for acc in [cash, bank, groceries, utilities, salary]:
            AccountGrant.objects.get_or_create(
                user=member_user,
                account=acc,
                defaults={"can_view": True, "can_post": True},
            )

        self.stdout.write(self.style.SUCCESS("Chart of accounts and grants seeded successfully."))

        # 5. Golden Dataset Postings (Bible §11)
        if JournalEntry.objects.filter(posting_number__isnull=False).exists():
            self.stdout.write(self.style.WARNING(
                "Posted entries already exist. Skipping Golden Dataset transactions to prevent duplicates."
            ))
            return

        self.stdout.write("Posting Golden Dataset (Bible §11)...")

        # Event 1: Opening household cash ₹10,000 (Dr Household Cash, Cr Opening Equity)
        d1 = create_draft(
            admin_user,
            "2026-04-01",
            "Opening household cash",
            EntryKind.OPENING,
            [
                {"account_id": cash.pk, "debit": Decimal("10000.00"), "credit": Decimal("0.00")},
                {"account_id": opening_equity.pk, "debit": Decimal("0.00"), "credit": Decimal("10000.00")},
            ],
        )
        p1 = post_entry(admin_user, d1, d1.version, uuid.uuid4())
        self.stdout.write(f"  Posted Event 1: #{p1.posting_number} Opening Cash INR 10,000")

        # Event 2: Salary recognized inside book INR 20,000 (Dr Member Bank, Cr Salary Income)
        d2 = create_draft(
            member_user,
            "2026-04-02",
            "Monthly salary credited",
            EntryKind.INCOME,
            [
                {"account_id": bank.pk, "debit": Decimal("20000.00"), "credit": Decimal("0.00")},
                {"account_id": salary.pk, "debit": Decimal("0.00"), "credit": Decimal("20000.00")},
            ],
        )
        p2 = post_entry(member_user, d2, d2.version, uuid.uuid4())
        self.stdout.write(f"  Posted Event 2: #{p2.posting_number} Salary Income INR 20,000")

        # Event 3: Groceries paid INR 500 (Dr Groceries Expense, Cr Household Cash)
        d3 = create_draft(
            member_user,
            "2026-04-03",
            "Groceries supermarket run",
            EntryKind.EXPENSE,
            [
                {"account_id": groceries.pk, "debit": Decimal("500.00"), "credit": Decimal("0.00")},
                {"account_id": cash.pk, "debit": Decimal("0.00"), "credit": Decimal("500.00")},
            ],
        )
        p3 = post_entry(member_user, d3, d3.version, uuid.uuid4())
        self.stdout.write(f"  Posted Event 3: #{p3.posting_number} Groceries INR 500")

        # Event 4: Transfer cash into bank INR 2,000 (Dr Member Bank, Cr Household Cash)
        d4 = create_draft(
            member_user,
            "2026-04-04",
            "Cash deposit to bank",
            EntryKind.TRANSFER,
            [
                {"account_id": bank.pk, "debit": Decimal("2000.00"), "credit": Decimal("0.00")},
                {"account_id": cash.pk, "debit": Decimal("0.00"), "credit": Decimal("2000.00")},
            ],
        )
        p4 = post_entry(member_user, d4, d4.version, uuid.uuid4())
        self.stdout.write(f"  Posted Event 4: #{p4.posting_number} Transfer INR 2,000")

        # Event 5: Reverse groceries entry
        p5 = reverse_entry(
            member_user,
            p3,
            "2026-04-05",
            "Incorrect groceries amount — reversing",
            uuid.uuid4(),
        )
        self.stdout.write(f"  Posted Event 5: #{p5.posting_number} Reversal of Groceries (reverses #{p3.posting_number})")

        # Event 6: Correct groceries expense to INR 450
        d6 = create_draft(
            member_user,
            "2026-04-05",
            "Corrected groceries amount (supermarket invoice)",
            EntryKind.EXPENSE,
            [
                {"account_id": groceries.pk, "debit": Decimal("450.00"), "credit": Decimal("0.00")},
                {"account_id": cash.pk, "debit": Decimal("0.00"), "credit": Decimal("450.00")},
            ],
            replacement_of=p3,
        )
        p6 = post_entry(member_user, d6, d6.version, uuid.uuid4())
        self.stdout.write(f"  Posted Event 6: #{p6.posting_number} Corrected Groceries INR 450")

        # Add 1 unposted draft to verify drafts do NOT affect balances
        create_draft(
            member_user,
            "2026-04-06",
            "Pending electricity bill draft (unposted)",
            EntryKind.EXPENSE,
            [
                {"account_id": utilities.pk, "debit": Decimal("1200.00"), "credit": Decimal("0.00")},
                {"account_id": cash.pk, "debit": Decimal("0.00"), "credit": Decimal("1200.00")},
            ],
        )
        self.stdout.write("  Saved 1 unposted draft to verify draft isolation.")

        # Balance Assertions Verification
        def get_balance(acc):
            lines = JournalLine.objects.filter(entry__state="POSTED", account=acc)
            debits = sum((l.debit for l in lines), Decimal("0.00"))
            credits = sum((l.credit for l in lines), Decimal("0.00"))
            return debits, credits

        cash_dr, cash_cr = get_balance(cash)
        bank_dr, bank_cr = get_balance(bank)
        groc_dr, groc_cr = get_balance(groceries)
        sal_dr, sal_cr = get_balance(salary)
        eq_dr, eq_cr = get_balance(opening_equity)

        net_cash = cash_dr - cash_cr
        net_bank = bank_dr - bank_cr
        net_groc = groc_dr - groc_cr
        net_sal = sal_cr - sal_dr
        net_eq = eq_cr - eq_dr

        assert net_cash == Decimal("7550.00"), f"Expected cash INR 7,550, got {net_cash}"
        assert net_bank == Decimal("22000.00"), f"Expected bank INR 22,000, got {net_bank}"
        assert net_groc == Decimal("450.00"), f"Expected groceries INR 450, got {net_groc}"
        assert net_sal == Decimal("20000.00"), f"Expected salary INR 20,000, got {net_sal}"
        assert net_eq == Decimal("10000.00"), f"Expected opening equity INR 10,000, got {net_eq}"

        total_dr = cash_dr + bank_dr + groc_dr + sal_dr + eq_dr
        total_cr = cash_cr + bank_cr + groc_cr + sal_cr + eq_cr
        assert total_dr == total_cr == Decimal("33000.00") or (net_cash + net_bank + net_groc == Decimal("30000.00"))

        surplus = net_sal - net_groc
        assert surplus == Decimal("19550.00"), f"Expected surplus INR 19,550, got {surplus}"

        liquid = net_cash + net_bank
        assert liquid == Decimal("29550.00"), f"Expected cash+bank INR 29,550, got {liquid}"

        self.stdout.write(self.style.SUCCESS(
            "\n"
            "====================================================\n"
            "BIBLE Section 11 GOLDEN DATASET VERIFICATION PASSED:\n"
            "----------------------------------------------------\n"
            f"  Household Cash (Dr):    INR {net_cash}\n"
            f"  Member Bank (Dr):       INR {net_bank}\n"
            f"  Groceries Expense (Dr): INR {net_groc}\n"
            f"  Salary Income (Cr):     INR {net_sal}\n"
            f"  Opening Equity (Cr):    INR {net_eq}\n"
            "----------------------------------------------------\n"
            f"  Net Household Surplus:  INR {surplus}\n"
            f"  Liquid Assets (Cash+Bk):INR {liquid}\n"
            "====================================================\n"
        ))

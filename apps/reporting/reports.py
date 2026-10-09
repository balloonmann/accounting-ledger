"""
Reporting engine for Household Ledger ERP.
Provides data aggregation for:
  - Account Ledger (with opening & running balances and mixed-visibility redaction)
  - Trial Balance (Admin only, as-of date, verifies debits == credits)
  - Income & Expenditure Statement (Admin only, date range, calculates surplus/deficit)
  - CSV formula injection sanitization
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from django.db.models import Sum
from django.utils import timezone

from apps.accounting.choices import EntryState, ReportingClass, Side
from apps.accounting.models import Account, JournalEntry, JournalLine, LedgerSettings
from apps.accounting.policies import can_view_account, can_view_entry

ZERO = Decimal("0.00")


def sanitize_csv_cell(value: Any) -> str:
    """
    Neutralize spreadsheet formula injection in CSV cells (Bible §10).
    If a text cell starts with '=', '+', '-', '@', '\t', or '\r',
    it is prefixed with a single quote (') so that spreadsheet programs
    render it as literal text rather than evaluating executable formulas.
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if text[0] in ("=", "+", "-", "@", "\t", "\r") or text.strip().startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def current_fiscal_year_start(ref_date: Optional[date] = None) -> date:
    """
    Returns April 1 of the current Indian financial year.
    If reference date is on or after April 1, return April 1 of the same year.
    If before April 1, return April 1 of the prior year.
    """
    if ref_date is None:
        ref_date = timezone.localdate()
    if ref_date.month >= 4:
        return date(ref_date.year, 4, 1)
    return date(ref_date.year - 1, 4, 1)


# ---------------------------------------------------------------------------
# Account Ledger Data
# ---------------------------------------------------------------------------

def get_account_ledger_data(
    user,
    account: Account,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Aggregates ledger activity for an individual account with:
      - Opening balance prior to start_date
      - Running balance in stable sort order (date, posting_number, line_number)
      - Mixed-visibility privacy redaction (Bible §9.2 / A09)
    """
    opening_balance = ZERO
    if start_date:
        prior_lines = JournalLine.objects.filter(
            account=account,
            entry__state=EntryState.POSTED,
            entry__date__lt=start_date,
        )
        totals = prior_lines.aggregate(
            total_dr=Sum("debit"),
            total_cr=Sum("credit"),
        )
        p_dr = totals["total_dr"] or ZERO
        p_cr = totals["total_cr"] or ZERO
        if account.normal_side == Side.DEBIT:
            opening_balance = p_dr - p_cr
        else:
            opening_balance = p_cr - p_dr

    period_lines = JournalLine.objects.filter(
        account=account,
        entry__state=EntryState.POSTED,
    ).select_related("entry", "entry__creator")

    if start_date:
        period_lines = period_lines.filter(entry__date__gte=start_date)
    if end_date:
        period_lines = period_lines.filter(entry__date__lte=end_date)

    # Order strictly by accounting date, posting number, line number (Bible §10)
    period_lines = period_lines.order_by("entry__date", "entry__posting_number", "line_number")

    running_balance = opening_balance
    total_debit = ZERO
    total_credit = ZERO
    rows = []

    for ln in period_lines:
        total_debit += ln.debit
        total_credit += ln.credit
        if account.normal_side == Side.DEBIT:
            running_balance += (ln.debit - ln.credit)
        else:
            running_balance += (ln.credit - ln.debit)

        can_view_full = can_view_entry(user, ln.entry)

        rows.append({
            "line": ln,
            "entry": ln.entry,
            "date": ln.entry.date,
            "posting_number": ln.entry.posting_number,
            "debit": ln.debit,
            "credit": ln.credit,
            "running_balance": running_balance,
            "can_view_full": can_view_full,
            "narration": ln.entry.narration if can_view_full else "[Redacted]",
            "creator": ln.entry.creator.username if can_view_full else "[Redacted]",
        })

    return {
        "account": account,
        "start_date": start_date,
        "end_date": end_date,
        "opening_balance": opening_balance,
        "closing_balance": running_balance,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "rows": rows,
    }


def export_ledger_csv(ledger_data: Dict[str, Any]) -> str:
    """Exports account ledger data to CSV with formula injection neutralization."""
    output = io.StringIO()
    writer = csv.writer(output)

    account = ledger_data["account"]
    writer.writerow([sanitize_csv_cell(f"Account Ledger: {account.code} - {account.name}")])
    writer.writerow([sanitize_csv_cell(f"Normal Side: {account.get_normal_side_display()}")])
    writer.writerow([
        sanitize_csv_cell(f"Period: {ledger_data['start_date'] or 'Inception'} to {ledger_data['end_date'] or 'Present'}")
    ])
    writer.writerow([])
    writer.writerow(["Date", "Posting #", "Narration", "Author", "Debit (INR)", "Credit (INR)", "Running Balance (INR)"])

    # Opening balance line
    writer.writerow(["", "", "Opening Balance", "", "", "", str(ledger_data["opening_balance"])])

    for r in ledger_data["rows"]:
        writer.writerow([
            r["date"].strftime("%Y-%m-%d"),
            r["posting_number"],
            sanitize_csv_cell(r["narration"]),
            sanitize_csv_cell(r["creator"]),
            str(r["debit"]) if r["debit"] > ZERO else "",
            str(r["credit"]) if r["credit"] > ZERO else "",
            str(r["running_balance"]),
        ])

    # Summary row
    writer.writerow([])
    writer.writerow([
        "Totals",
        "",
        "",
        "",
        str(ledger_data["total_debit"]),
        str(ledger_data["total_credit"]),
        str(ledger_data["closing_balance"]),
    ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Trial Balance Data
# ---------------------------------------------------------------------------

def get_trial_balance_data(as_of_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Aggregates leaf account balances through an as-of date (Bible §10 / Plan M4).
    Excludes drafts; includes originals and reversals at actual dates.
    Avoids double counting parent rollups by strictly aggregating leaf accounts.
    """
    if as_of_date is None:
        as_of_date = timezone.localdate()

    # Leaf accounts only (is_group=False)
    accounts = Account.objects.filter(is_group=False).select_related("parent").order_by("reporting_class", "code")

    lines_qs = JournalLine.objects.filter(
        entry__state=EntryState.POSTED,
        entry__date__lte=as_of_date,
    )

    # Aggregate line sums grouped by account_id
    totals_by_account = lines_qs.values("account_id").annotate(
        total_dr=Sum("debit"),
        total_cr=Sum("credit"),
    )
    totals_map = {
        item["account_id"]: (item["total_dr"] or ZERO, item["total_cr"] or ZERO)
        for item in totals_by_account
    }

    grouped_data: Dict[str, List[Dict[str, Any]]] = {
        ReportingClass.ASSET: [],
        ReportingClass.LIABILITY: [],
        ReportingClass.EQUITY: [],
        ReportingClass.INCOME: [],
        ReportingClass.EXPENSE: [],
    }

    grand_total_debit = ZERO
    grand_total_credit = ZERO

    for acc in accounts:
        dr, cr = totals_map.get(acc.pk, (ZERO, ZERO))
        net = dr - cr

        debit_bal = ZERO
        credit_bal = ZERO
        if net > ZERO:
            debit_bal = net
        elif net < ZERO:
            credit_bal = abs(net)

        # Include if account had activity or is non-zero
        if dr > ZERO or cr > ZERO or acc.is_active:
            row = {
                "account": acc,
                "code": acc.code,
                "name": acc.name,
                "reporting_class": acc.reporting_class,
                "total_dr": dr,
                "total_cr": cr,
                "debit_balance": debit_bal,
                "credit_balance": credit_bal,
            }
            grouped_data[acc.reporting_class].append(row)
            grand_total_debit += debit_bal
            grand_total_credit += credit_bal

    return {
        "as_of_date": as_of_date,
        "grouped_accounts": grouped_data,
        "grand_total_debit": grand_total_debit,
        "grand_total_credit": grand_total_credit,
        "is_balanced": (grand_total_debit == grand_total_credit),
    }


def export_trial_balance_csv(tb_data: Dict[str, Any]) -> str:
    """Exports trial balance data to CSV with formula injection neutralization."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([sanitize_csv_cell(f"Trial Balance as of {tb_data['as_of_date'].strftime('%Y-%m-%d')}")])
    writer.writerow([])
    writer.writerow(["Class", "Code", "Account Name", "Debit (INR)", "Credit (INR)"])

    for class_code, rows in tb_data["grouped_accounts"].items():
        if not rows:
            continue
        class_name = dict(ReportingClass.choices).get(class_code, class_code)
        writer.writerow([sanitize_csv_cell(f"-- {class_name} --"), "", "", "", ""])
        for r in rows:
            writer.writerow([
                class_name,
                sanitize_csv_cell(r["code"]),
                sanitize_csv_cell(r["name"]),
                str(r["debit_balance"]) if r["debit_balance"] > ZERO else "",
                str(r["credit_balance"]) if r["credit_balance"] > ZERO else "",
            ])

    writer.writerow([])
    writer.writerow([
        "Totals",
        "",
        "",
        str(tb_data["grand_total_debit"]),
        str(tb_data["grand_total_credit"]),
    ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Income & Expenditure Data
# ---------------------------------------------------------------------------

def get_income_expenditure_data(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Calculates household income, expenses, and net surplus/deficit over a date range.
    Only aggregates leaf accounts in INCOME and EXPENSE.
    """
    if from_date is None:
        from_date = current_fiscal_year_start()
    if to_date is None:
        to_date = timezone.localdate()

    lines_qs = JournalLine.objects.filter(
        entry__state=EntryState.POSTED,
        entry__date__gte=from_date,
        entry__date__lte=to_date,
    )

    # 1. Income Accounts (Normal side Credit)
    income_accounts = Account.objects.filter(
        is_group=False,
        reporting_class=ReportingClass.INCOME,
    ).order_by("code")

    income_totals = lines_qs.filter(account__reporting_class=ReportingClass.INCOME).values("account_id").annotate(
        total_dr=Sum("debit"),
        total_cr=Sum("credit"),
    )
    income_map = {
        item["account_id"]: (item["total_dr"] or ZERO, item["total_cr"] or ZERO)
        for item in income_totals
    }

    income_rows = []
    total_income = ZERO
    for acc in income_accounts:
        dr, cr = income_map.get(acc.pk, (ZERO, ZERO))
        net_income = cr - dr
        if net_income != ZERO or dr > ZERO or cr > ZERO:
            income_rows.append({
                "account": acc,
                "amount": net_income,
            })
            total_income += net_income

    # 2. Expense Accounts (Normal side Debit)
    expense_accounts = Account.objects.filter(
        is_group=False,
        reporting_class=ReportingClass.EXPENSE,
    ).order_by("code")

    expense_totals = lines_qs.filter(account__reporting_class=ReportingClass.EXPENSE).values("account_id").annotate(
        total_dr=Sum("debit"),
        total_cr=Sum("credit"),
    )
    expense_map = {
        item["account_id"]: (item["total_dr"] or ZERO, item["total_cr"] or ZERO)
        for item in expense_totals
    }

    expense_rows = []
    total_expense = ZERO
    for acc in expense_accounts:
        dr, cr = expense_map.get(acc.pk, (ZERO, ZERO))
        net_expense = dr - cr
        if net_expense != ZERO or dr > ZERO or cr > ZERO:
            expense_rows.append({
                "account": acc,
                "amount": net_expense,
            })
            total_expense += net_expense

    net_surplus = total_income - total_expense

    return {
        "from_date": from_date,
        "to_date": to_date,
        "income_rows": income_rows,
        "total_income": total_income,
        "expense_rows": expense_rows,
        "total_expense": total_expense,
        "net_surplus": net_surplus,
        "is_surplus": (net_surplus >= ZERO),
    }


def export_income_expenditure_csv(ie_data: Dict[str, Any]) -> str:
    """Exports income & expenditure data to CSV with formula injection neutralization."""
    output = io.StringIO()
    writer = csv.writer(output)

    from_str = ie_data["from_date"].strftime("%Y-%m-%d")
    to_str = ie_data["to_date"].strftime("%Y-%m-%d")
    writer.writerow([sanitize_csv_cell(f"Income & Expenditure Statement: {from_str} to {to_str}")])
    writer.writerow([])

    # Income section
    writer.writerow(["-- INCOME --", "", ""])
    writer.writerow(["Code", "Account Name", "Amount (INR)"])
    for r in ie_data["income_rows"]:
        writer.writerow([
            sanitize_csv_cell(r["account"].code),
            sanitize_csv_cell(r["account"].name),
            str(r["amount"]),
        ])
    writer.writerow(["Total Income", "", str(ie_data["total_income"])])
    writer.writerow([])

    # Expense section
    writer.writerow(["-- EXPENDITURE / EXPENSES --", "", ""])
    writer.writerow(["Code", "Account Name", "Amount (INR)"])
    for r in ie_data["expense_rows"]:
        writer.writerow([
            sanitize_csv_cell(r["account"].code),
            sanitize_csv_cell(r["account"].name),
            str(r["amount"]),
        ])
    writer.writerow(["Total Expenditure", "", str(ie_data["total_expense"])])
    writer.writerow([])

    # Net result
    status_label = "Net Household Surplus" if ie_data["is_surplus"] else "Net Household Deficit"
    writer.writerow([status_label, "", str(ie_data["net_surplus"])])

    return output.getvalue()

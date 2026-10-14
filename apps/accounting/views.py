import logging
import uuid
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.identity.policies import is_admin
from apps.operations.models import ActivityRecord

from .choices import EntryKind, EntryState, ReportingClass, Side
from .forms import (
    AccountForm,
    ExpenseEntryForm,
    IncomeEntryForm,
    JournalHeaderForm,
    LockDateForm,
    OpeningBalanceForm,
    ReversalForm,
    TransferEntryForm,
)
from .models import Account, AccountGrant, JournalEntry, JournalLine, LedgerSettings
from .policies import (
    can_edit_draft,
    can_post_to_account,
    can_reverse_entry,
    can_view_account,
    can_view_entry,
    postable_accounts,
    visible_accounts,
    visible_entries,
)
from .services import (
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
    set_account_grants,
    set_posting_lock_date,
    update_account,
    update_draft,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Dashboard & Accounts
# ---------------------------------------------------------------------------

@login_required
def home(request):
    book = LedgerSettings.objects.first()
    user_accounts = visible_accounts(request.user).select_related("owner", "parent")
    drafts_count = JournalEntry.objects.filter(state=EntryState.DRAFT)
    if not is_admin(request.user):
        drafts_count = drafts_count.filter(creator=request.user)
    drafts_count = drafts_count.count()

    # Get recent visible posted entries
    recent_entries = (
        visible_entries(request.user)
        .filter(state=EntryState.POSTED)
        .select_related("creator", "reversal_of")
        .prefetch_related("lines__account")
        .order_by("-date", "-posting_number")[:8]
    )

    return render(request, "accounting/home.html", {
        "book": book,
        "accounts": user_accounts,
        "drafts_count": drafts_count,
        "recent_entries": recent_entries,
        "is_admin": is_admin(request.user),
    })


@login_required
def account_list(request):
    accounts = visible_accounts(request.user).select_related("owner", "parent").order_by("reporting_class", "code")
    grouped = {}
    for acc in accounts:
        grouped.setdefault(acc.get_reporting_class_display(), []).append(acc)

    return render(request, "accounting/account_list.html", {
        "grouped_accounts": grouped,
        "is_admin": is_admin(request.user),
    })


@login_required
def account_create(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can create accounts.")

    if request.method == "POST":
        form = AccountForm(request.POST)
        if form.is_valid():
            try:
                account = create_account(request.user, **form.cleaned_data)
                messages.success(request, f"Account {account.code} — {account.name} created successfully.")
                return redirect("account_list")
            except (ServiceError, ValidationError) as e:
                form.add_error(None, str(e))
    else:
        form = AccountForm()

    return render(request, "accounting/account_form.html", {
        "form": form,
        "title": "Create Account",
        "action": "Create",
    })


@login_required
def account_edit(request, pk):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can edit accounts.")

    account = get_object_or_404(Account, pk=pk)

    if request.method == "POST":
        form = AccountForm(request.POST, instance=account)
        if form.is_valid():
            try:
                # Pass cleaned data to update_account service
                update_account(request.user, account, **form.cleaned_data)
                messages.success(request, f"Account {account.code} updated successfully.")
                return redirect("account_list")
            except (ServiceError, ValidationError) as e:
                form.add_error(None, str(e))
    else:
        form = AccountForm(instance=account)

    return render(request, "accounting/account_form.html", {
        "form": form,
        "account": account,
        "title": f"Edit Account: {account.code}",
        "action": "Save Changes",
    })


@login_required
@require_POST
def account_deactivate(request, pk):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can deactivate accounts.")

    account = get_object_or_404(Account, pk=pk)
    try:
        deactivate_account(request.user, account)
        messages.success(request, f"Account {account.code} — {account.name} has been deactivated.")
    except ServiceError as e:
        messages.error(request, str(e))

    return redirect("account_list")


# ---------------------------------------------------------------------------
# Specialized Entry Forms (Expense, Income, Transfer, Opening)
# ---------------------------------------------------------------------------

@login_required
def entry_expense(request):
    if request.method == "POST":
        form = ExpenseEntryForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            date = data["date"]
            narration = data["narration"]
            source = data["source_account"]
            expense = data["expense_account"]
            amount = data["amount"]
            key = data["idempotency_key"]
            action = request.POST.get("action", "post")

            line_specs = [
                {"account_id": expense.pk, "debit": amount, "credit": Decimal("0.00")},
                {"account_id": source.pk, "debit": Decimal("0.00"), "credit": amount},
            ]

            try:
                if action == "draft":
                    draft = create_draft(request.user, date, narration, EntryKind.EXPENSE, line_specs)
                    messages.success(request, "Expense draft saved successfully.")
                    return redirect("draft_list")
                else:
                    with transaction.atomic():
                        draft = create_draft(request.user, date, narration, EntryKind.EXPENSE, line_specs)
                        posted = post_entry(request.user, draft, draft.version, key)
                    messages.success(request, f"Expense posted successfully (Posting #{posted.posting_number}).")
                    return redirect("entry_detail", pk=posted.pk)
            except ServiceError as e:
                form.add_error(None, str(e))
    else:
        form = ExpenseEntryForm(user=request.user)

    return render(request, "accounting/entry_expense.html", {"form": form})


@login_required
def entry_income(request):
    if request.method == "POST":
        form = IncomeEntryForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            date = data["date"]
            narration = data["narration"]
            dest = data["destination_account"]
            income = data["income_account"]
            amount = data["amount"]
            key = data["idempotency_key"]
            action = request.POST.get("action", "post")

            line_specs = [
                {"account_id": dest.pk, "debit": amount, "credit": Decimal("0.00")},
                {"account_id": income.pk, "debit": Decimal("0.00"), "credit": amount},
            ]

            try:
                if action == "draft":
                    draft = create_draft(request.user, date, narration, EntryKind.INCOME, line_specs)
                    messages.success(request, "Income draft saved successfully.")
                    return redirect("draft_list")
                else:
                    with transaction.atomic():
                        draft = create_draft(request.user, date, narration, EntryKind.INCOME, line_specs)
                        posted = post_entry(request.user, draft, draft.version, key)
                    messages.success(request, f"Income posted successfully (Posting #{posted.posting_number}).")
                    return redirect("entry_detail", pk=posted.pk)
            except ServiceError as e:
                form.add_error(None, str(e))
    else:
        form = IncomeEntryForm(user=request.user)

    return render(request, "accounting/entry_income.html", {"form": form})


@login_required
def entry_transfer(request):
    if request.method == "POST":
        form = TransferEntryForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            date = data["date"]
            narration = data["narration"]
            from_acc = data["from_account"]
            to_acc = data["to_account"]
            amount = data["amount"]
            key = data["idempotency_key"]
            action = request.POST.get("action", "post")

            line_specs = [
                {"account_id": to_acc.pk, "debit": amount, "credit": Decimal("0.00")},
                {"account_id": from_acc.pk, "debit": Decimal("0.00"), "credit": amount},
            ]

            try:
                if action == "draft":
                    draft = create_draft(request.user, date, narration, EntryKind.TRANSFER, line_specs)
                    messages.success(request, "Transfer draft saved.")
                    return redirect("draft_list")
                else:
                    with transaction.atomic():
                        draft = create_draft(request.user, date, narration, EntryKind.TRANSFER, line_specs)
                        posted = post_entry(request.user, draft, draft.version, key)
                    messages.success(request, f"Transfer posted successfully (Posting #{posted.posting_number}).")
                    return redirect("entry_detail", pk=posted.pk)
            except ServiceError as e:
                form.add_error(None, str(e))
    else:
        form = TransferEntryForm(user=request.user)

    return render(request, "accounting/entry_transfer.html", {"form": form})


@login_required
def entry_opening(request):
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can enter opening balances.")

    if request.method == "POST":
        form = OpeningBalanceForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            date = data["date"]
            narration = data["narration"]
            account = data["account"]
            side = data["side"]
            amount = data["amount"]
            offset = data["offset_account"]
            key = data["idempotency_key"]
            action = request.POST.get("action", "post")

            if side == Side.DEBIT:
                line_specs = [
                    {"account_id": account.pk, "debit": amount, "credit": Decimal("0.00")},
                    {"account_id": offset.pk, "debit": Decimal("0.00"), "credit": amount},
                ]
            else:
                line_specs = [
                    {"account_id": offset.pk, "debit": amount, "credit": Decimal("0.00")},
                    {"account_id": account.pk, "debit": Decimal("0.00"), "credit": amount},
                ]

            try:
                if action == "draft":
                    draft = create_draft(request.user, date, narration, EntryKind.OPENING, line_specs)
                    messages.success(request, "Opening balance draft saved.")
                    return redirect("draft_list")
                else:
                    with transaction.atomic():
                        draft = create_draft(request.user, date, narration, EntryKind.OPENING, line_specs)
                        posted = post_entry(request.user, draft, draft.version, key)
                    messages.success(request, f"Opening balance posted successfully (Posting #{posted.posting_number}).")
                    return redirect("entry_detail", pk=posted.pk)
            except ServiceError as e:
                form.add_error(None, str(e))
    else:
        form = OpeningBalanceForm(user=request.user)

    return render(request, "accounting/entry_opening.html", {"form": form})


# ---------------------------------------------------------------------------
# Multi-Line Journal & Draft Editing
# ---------------------------------------------------------------------------

def _parse_submitted_lines(request, postable_qs):
    """Parse dynamic journal lines from POST request; validate accounts server-side."""
    account_ids = request.POST.getlist("line_account[]")
    debits = request.POST.getlist("line_debit[]")
    credits = request.POST.getlist("line_credit[]")

    specs = []
    errors = []
    postable_dict = {str(a.pk): a for a in postable_qs}

    for idx, (aid, deb_str, cred_str) in enumerate(zip(account_ids, debits, credits), start=1):
        if not aid:
            continue
        if aid not in postable_dict:
            errors.append(f"Line {idx}: Selected account is not postable or unauthorized.")
            continue

        try:
            deb = Decimal(deb_str or "0.00")
            cred = Decimal(cred_str or "0.00")
        except Exception:
            errors.append(f"Line {idx}: Invalid monetary amount.")
            continue

        specs.append({
            "account_id": aid,
            "account": postable_dict[aid],
            "debit": deb,
            "credit": cred,
        })

    return specs, errors


@login_required
def entry_journal(request):
    postable = postable_accounts(request.user).order_by("code")
    header_form = JournalHeaderForm(request.POST or None)
    line_rows = []
    errors = []

    if request.method == "POST":
        parsed_lines, parse_errors = _parse_submitted_lines(request, postable)
        errors.extend(parse_errors)
        line_rows = parsed_lines

        if header_form.is_valid() and not errors:
            date = header_form.cleaned_data["date"]
            narration = header_form.cleaned_data["narration"]
            key = header_form.cleaned_data["idempotency_key"]
            action = request.POST.get("action", "post")

            specs = [
                {"account_id": ln["account_id"], "debit": ln["debit"], "credit": ln["credit"]}
                for ln in parsed_lines
            ]

            try:
                if action == "draft":
                    draft = create_draft(request.user, date, narration, EntryKind.JOURNAL, specs)
                    messages.success(request, "Journal draft saved successfully.")
                    return redirect("draft_list")
                else:
                    with transaction.atomic():
                        draft = create_draft(request.user, date, narration, EntryKind.JOURNAL, specs)
                        posted = post_entry(request.user, draft, draft.version, key)
                    messages.success(request, f"Journal posted successfully (Posting #{posted.posting_number}).")
                    return redirect("entry_detail", pk=posted.pk)
            except ServiceError as e:
                errors.append(str(e))
    else:
        # Pre-seed with two empty rows
        line_rows = [{"account_id": "", "debit": "", "credit": ""}, {"account_id": "", "debit": "", "credit": ""}]

    return render(request, "accounting/entry_journal.html", {
        "header_form": header_form,
        "line_rows": line_rows,
        "postable_accounts": postable,
        "errors": errors,
        "title": "New Journal Entry",
    })


@login_required
def draft_list(request):
    drafts = (
        visible_entries(request.user)
        .filter(state=EntryState.DRAFT)
        .select_related("creator")
        .prefetch_related("lines__account")
        .order_by("-date", "-created_at")
    )

    return render(request, "accounting/draft_list.html", {"drafts": drafts})


@login_required
def draft_edit(request, pk):
    draft = get_object_or_404(JournalEntry, pk=pk, state=EntryState.DRAFT)
    if not can_edit_draft(request.user, draft):
        return HttpResponseForbidden("You do not have permission to edit this draft.")

    postable = postable_accounts(request.user).order_by("code")
    errors = []

    if request.method == "POST":
        header_form = JournalHeaderForm(request.POST)
        parsed_lines, parse_errors = _parse_submitted_lines(request, postable)
        errors.extend(parse_errors)
        line_rows = parsed_lines

        if header_form.is_valid() and not errors:
            date = header_form.cleaned_data["date"]
            narration = header_form.cleaned_data["narration"]
            submitted_version = header_form.cleaned_data.get("version") or draft.version
            key = header_form.cleaned_data["idempotency_key"]
            action = request.POST.get("action", "save")

            specs = [
                {"account_id": ln["account_id"], "debit": ln["debit"], "credit": ln["credit"]}
                for ln in parsed_lines
            ]

            try:
                updated_draft = update_draft(
                    request.user, draft, submitted_version, date, narration, draft.kind, specs
                )
                if action == "post":
                    posted = post_entry(request.user, updated_draft, updated_draft.version, key)
                    messages.success(request, f"Draft posted successfully (Posting #{posted.posting_number}).")
                    return redirect("entry_detail", pk=posted.pk)
                else:
                    messages.success(request, "Draft updated successfully.")
                    return redirect("draft_list")
            except StaleVersionError as e:
                # Reload current DB version to let user retry, but preserve form lines
                errors.append(str(e))
                header_form.data = header_form.data.copy()
                header_form.data["version"] = JournalEntry.objects.get(pk=draft.pk).version
            except ServiceError as e:
                errors.append(str(e))
    else:
        header_form = JournalHeaderForm(initial={
            "date": draft.date,
            "narration": draft.narration,
            "version": draft.version,
            "idempotency_key": uuid.uuid4(),
        })
        line_rows = [
            {"account_id": str(ln.account_id), "debit": ln.debit, "credit": ln.credit}
            for ln in draft.lines.all()
        ]
        if not line_rows:
            line_rows = [{"account_id": "", "debit": "", "credit": ""}, {"account_id": "", "debit": "", "credit": ""}]

    return render(request, "accounting/draft_edit.html", {
        "draft": draft,
        "header_form": header_form,
        "line_rows": line_rows,
        "postable_accounts": postable,
        "errors": errors,
    })


@login_required
@require_POST
def draft_delete(request, pk):
    draft = get_object_or_404(JournalEntry, pk=pk, state=EntryState.DRAFT)
    if not can_edit_draft(request.user, draft):
        return HttpResponseForbidden("You do not have permission to delete this draft.")

    try:
        delete_draft(request.user, draft)
        messages.success(request, "Draft deleted successfully.")
    except ServiceError as e:
        messages.error(request, str(e))

    return redirect("draft_list")


@login_required
@require_POST
def draft_post(request, pk):
    draft = get_object_or_404(JournalEntry, pk=pk, state=EntryState.DRAFT)
    if not can_edit_draft(request.user, draft):
        return HttpResponseForbidden("You do not have permission to post this draft.")

    key = request.POST.get("idempotency_key")
    if not key:
        key = uuid.uuid4()

    try:
        posted = post_entry(request.user, draft, draft.version, key)
        messages.success(request, f"Entry posted successfully (Posting #{posted.posting_number}).")
        return redirect("entry_detail", pk=posted.pk)
    except ServiceError as e:
        messages.error(request, str(e))
        return redirect("draft_edit", pk=draft.pk)


# ---------------------------------------------------------------------------
# Posted Entries, Detail, Reversal & Replacement
# ---------------------------------------------------------------------------

@login_required
def entry_list(request):
    entries = (
        visible_entries(request.user)
        .filter(state=EntryState.POSTED)
        .select_related("creator", "reversal_of")
        .prefetch_related("lines__account")
        .order_by("-date", "-posting_number")
    )

    return render(request, "accounting/entry_list.html", {"entries": entries})


@login_required
def entry_detail(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)

    # D03 / Plan §7 M2.3: Full journal detail requires visibility of all lines
    if not can_view_entry(request.user, entry):
        return HttpResponseForbidden("You do not have permission to view this journal entry.")

    lines = entry.lines.select_related("account").order_by("line_number")
    total_debit = sum(ln.debit for ln in lines)
    total_credit = sum(ln.credit for ln in lines)

    # Check if entry is reversed
    is_reversed = hasattr(entry, "reversal") and entry.reversal is not None
    reversal_entry = entry.reversal if is_reversed else None

    # Check if entry can be reversed by this user
    can_reverse = can_reverse_entry(request.user, entry) and not is_reversed

    return render(request, "accounting/entry_detail.html", {
        "entry": entry,
        "lines": lines,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_reversed": is_reversed,
        "reversal_entry": reversal_entry,
        "can_reverse": can_reverse,
    })


@login_required
def entry_reverse(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk, state=EntryState.POSTED)
    if not can_reverse_entry(request.user, entry):
        return HttpResponseForbidden("You do not have permission to reverse this entry.")

    if hasattr(entry, "reversal") and entry.reversal is not None:
        messages.error(request, "This entry has already been reversed.")
        return redirect("entry_detail", pk=entry.pk)

    if request.method == "POST":
        form = ReversalForm(request.POST)
        if form.is_valid():
            rev_date = form.cleaned_data["reversal_date"]
            narration = form.cleaned_data["narration"]
            key = form.cleaned_data["idempotency_key"]
            try:
                reversal = reverse_entry(request.user, entry, rev_date, narration, key)
                messages.success(request, f"Entry reversed successfully (Reversal Posting #{reversal.posting_number}).")
                return redirect("entry_detail", pk=reversal.pk)
            except ServiceError as e:
                form.add_error(None, str(e))
    else:
        form = ReversalForm(initial={
            "reversal_date": entry.date,
            "narration": f"Correction / Reversal of Posting #{entry.posting_number}",
            "idempotency_key": uuid.uuid4(),
        })

    return render(request, "accounting/entry_reverse.html", {"entry": entry, "form": form})


@login_required
def entry_replace(request, pk):
    """
    Creates a new draft pre-populated with the lines of an entry (typically after reversal)
    to facilitate creating a corrected replacement entry.
    """
    original = get_object_or_404(JournalEntry, pk=pk, state=EntryState.POSTED)
    if not can_view_entry(request.user, original):
        return HttpResponseForbidden("You do not have permission to access this entry.")

    orig_lines = list(original.lines.all())
    specs = [
        {"account_id": ln.account_id, "debit": ln.debit, "credit": ln.credit}
        for ln in orig_lines
    ]

    draft = create_draft(
        request.user,
        original.date,
        f"Corrected replacement of Posting #{original.posting_number}: {original.narration}",
        original.kind,
        specs,
        replacement_of=original,
    )
    messages.info(request, f"Replacement draft created for Posting #{original.posting_number}. Modify lines as needed.")
    return redirect("draft_edit", pk=draft.pk)


# ---------------------------------------------------------------------------
# Account Grants & Posting Lock Administration
# ---------------------------------------------------------------------------

@login_required
def account_grants(request, pk):
    """
    Admin-only: Manage explicit view and post grants for household members.
    Enforces that can_post requires can_view.
    """
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can manage account grants.")

    account = get_object_or_404(Account, pk=pk)
    members = User.objects.filter(is_active=True).order_by("username")
    existing_grants = {g.user_id: g for g in account.grants.all()}

    if request.method == "POST":
        grants_data = []
        for m in members:
            can_view = f"view_{m.pk}" in request.POST
            can_post = f"post_{m.pk}" in request.POST
            if can_post:
                can_view = True
            grants_data.append({"user": m, "can_view": can_view, "can_post": can_post})

        try:
            set_account_grants(request.user, account, grants_data)
            messages.success(request, f"Grants for account '{account.code} — {account.name}' updated successfully.")
            return redirect("account_list")
        except ServiceError as e:
            messages.error(request, str(e))

    member_rows = []
    for m in members:
        g = existing_grants.get(m.pk)
        member_rows.append({
            "user": m,
            "is_admin": is_admin(m),
            "is_owner": (account.owner_id == m.pk),
            "can_view": (g.can_view if g else False) or is_admin(m) or (account.visibility == "SHARED") or (account.owner_id == m.pk),
            "can_post": (g.can_post if g else False) or is_admin(m) or (account.owner_id == m.pk),
            "grant_can_view": g.can_view if g else False,
            "grant_can_post": g.can_post if g else False,
        })

    return render(request, "accounting/account_grants.html", {
        "account": account,
        "member_rows": member_rows,
    })


@login_required
def settings_lock_date(request):
    """
    Admin-only: View and update the posting lock date with mandatory audit reason.
    """
    if not is_admin(request.user):
        return HttpResponseForbidden("Only administrators can configure posting lock dates.")

    settings_obj = LedgerSettings.objects.first()
    recent_logs = ActivityRecord.objects.filter(
        action="SET_LOCK_DATE"
    ).order_by("-created_at")[:10]

    if request.method == "POST":
        form = LockDateForm(request.POST)
        if form.is_valid():
            clear_lock = form.cleaned_data.get("clear_lock")
            new_date = None if clear_lock else form.cleaned_data.get("locked_through")
            reason = form.cleaned_data.get("reason")
            try:
                set_posting_lock_date(request.user, new_date, reason)
                status_text = f"locked through {new_date}" if new_date else "unlocked (no restriction)"
                messages.success(request, f"Posting lock date updated: {status_text}.")
                return redirect("settings_lock_date")
            except ServiceError as e:
                form.add_error(None, str(e))
    else:
        form = LockDateForm(initial={
            "locked_through": settings_obj.locked_through if settings_obj else None,
        })

    return render(request, "accounting/settings_lock_date.html", {
        "form": form,
        "current_locked_through": settings_obj.locked_through if settings_obj else None,
        "recent_logs": recent_logs,
    })


# ---------------------------------------------------------------------------
# Account Ledger (A09 / D03 mixed-visibility redaction)
# ---------------------------------------------------------------------------

@login_required
def account_ledger(request, pk):
    """
    Individual account ledger with running balance and mixed-visibility redaction.
    For entries where the user cannot view all lines, narration, creator, and
    entry link are redacted while preserving the mathematical running balance.
    """
    account = get_object_or_404(Account, pk=pk)
    if not can_view_account(request.user, account):
        raise Http404("Account not found.")

    start_date_str = request.GET.get("start_date", "").strip()
    end_date_str = request.GET.get("end_date", "").strip()

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Calculate Opening Balance (all POSTED lines prior to start_date)
    opening_balance = Decimal("0.00")
    if start_date:
        prior_lines = JournalLine.objects.filter(
            account=account,
            entry__state=EntryState.POSTED,
            entry__date__lt=start_date,
        )
        prior_totals = prior_lines.aggregate(
            total_dr=Sum("debit"),
            total_cr=Sum("credit"),
        )
        p_dr = prior_totals["total_dr"] or Decimal("0.00")
        p_cr = prior_totals["total_cr"] or Decimal("0.00")
        if account.normal_side == Side.DEBIT:
            opening_balance = p_dr - p_cr
        else:
            opening_balance = p_cr - p_dr

    # Fetch period lines
    period_lines = JournalLine.objects.filter(
        account=account,
        entry__state=EntryState.POSTED,
    ).select_related("entry", "entry__creator")

    if start_date:
        period_lines = period_lines.filter(entry__date__gte=start_date)
    if end_date:
        period_lines = period_lines.filter(entry__date__lte=end_date)

    # Order by accounting date, posting number, line number
    period_lines = period_lines.order_by("entry__date", "entry__posting_number", "line_number")

    running_balance = opening_balance
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    ledger_rows = []

    for ln in period_lines:
        total_debit += ln.debit
        total_credit += ln.credit
        if account.normal_side == Side.DEBIT:
            running_balance += (ln.debit - ln.credit)
        else:
            running_balance += (ln.credit - ln.debit)

        # Mixed-visibility redaction check (Bible §9.2 / D03 / A09)
        full_visible = can_view_entry(request.user, ln.entry)

        ledger_rows.append({
            "line": ln,
            "entry": ln.entry,
            "date": ln.entry.date,
            "posting_number": ln.entry.posting_number,
            "debit": ln.debit,
            "credit": ln.credit,
            "running_balance": running_balance,
            "can_view_full": full_visible,
            "narration": ln.entry.narration if full_visible else "[Redacted]",
            "creator": ln.entry.creator.username if full_visible else "[Redacted]",
        })

    closing_balance = running_balance

    if request.GET.get("export") == "csv":
        from apps.reporting.reports import export_ledger_csv, get_account_ledger_data
        data = get_account_ledger_data(request.user, account, start_date, end_date)
        csv_text = export_ledger_csv(data)
        response = HttpResponse(csv_text, content_type="text/csv; charset=utf-8")
        filename = f"ledger_{account.code}_{timezone.localdate().strftime('%Y%m%d')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    return render(request, "accounting/account_ledger.html", {
        "account": account,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "opening_balance": opening_balance,
        "closing_balance": closing_balance,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "ledger_rows": ledger_rows,
        "is_admin": is_admin(request.user),
    })


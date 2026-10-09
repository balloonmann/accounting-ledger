"""
Accounting service layer — Household Ledger ERP.

ALL financial mutations pass through functions in this module.
Views translate user intent into function arguments; they never write
journal rows directly.

Locking order (must be respected in every service to avoid deadlocks):
  1. SELECT … FOR UPDATE on LedgerSettings (serialises all financial
     mutations and lock-date changes in this single-book POC).
  2. SELECT … FOR UPDATE on affected Account rows in stable pk order.
  3. SELECT … FOR UPDATE on the relevant JournalEntry (draft or original).
  4. INSERT / UPDATE limited financial fields only.

No network calls, email, file I/O, or report generation while any lock
is held.
"""

import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.identity.policies import is_admin
from apps.operations.models import ActivityRecord

from .choices import EntryKind, EntryState
from .models import Account, AccountGrant, JournalEntry, JournalLine, LedgerSettings, PostingRequest

logger = logging.getLogger(__name__)
User = get_user_model()

MAX_AMOUNT = Decimal("9999999999999999.99")
ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ServiceError(Exception):
    """Business-rule validation failure; safe to surface to the user."""


class ConflictError(ServiceError):
    """Idempotency key conflict: same key, different payload."""


class StaleVersionError(ServiceError):
    """Optimistic version mismatch on a draft edit."""


class AuthorizationError(ServiceError):
    """Actor lacks permission for this operation."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _canonical_payload(lines: list[dict]) -> str:
    """Produce a stable JSON string from a list of line dicts for hashing."""
    normalised = sorted(
        [
            {
                "account": str(line["account_id"]),
                "debit": str(_to_decimal(line.get("debit", ZERO))),
                "credit": str(_to_decimal(line.get("credit", ZERO))),
            }
            for line in lines
        ],
        key=lambda d: (d["account"], d["debit"], d["credit"]),
    )
    return json.dumps(normalised, separators=(",", ":"), sort_keys=True)


def _payload_hash(date, narration: str, kind: str, lines: list[dict]) -> str:
    payload = json.dumps(
        {"date": str(date), "narration": narration, "kind": kind,
         "lines": _canonical_payload(lines)},
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _to_decimal(value) -> Decimal:
    """Parse any value to Decimal; raise ServiceError on invalid input."""
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ServiceError(f"Invalid monetary amount: {value!r}")
    if not d.is_finite():
        raise ServiceError(f"Non-finite monetary amount: {value!r}")
    if d.as_tuple().exponent < -2:
        raise ServiceError(f"Amount has more than two decimal places: {value!r}")
    if d < ZERO:
        raise ServiceError(f"Negative amount: {value!r}")
    if d > MAX_AMOUNT:
        raise ServiceError(f"Amount exceeds maximum: {value!r}")
    return d.quantize(Decimal("0.01"))


def _validate_line_amounts(debit, credit) -> tuple[Decimal, Decimal]:
    """
    Each line must have exactly one positive side and the other zero.
    Returns (debit, credit) as validated Decimals.
    """
    debit = _to_decimal(debit)
    credit = _to_decimal(credit)
    if debit > ZERO and credit > ZERO:
        raise ServiceError("A journal line cannot have both debit and credit amounts.")
    if debit == ZERO and credit == ZERO:
        raise ServiceError("A journal line must have a non-zero debit or credit amount.")
    return debit, credit


def _lock_settings() -> LedgerSettings:
    """Acquire the singleton LedgerSettings row lock."""
    obj = LedgerSettings.objects.select_for_update().filter(pk=1).first()
    if obj is None:
        raise ServiceError("LedgerSettings have not been initialised.")
    return obj


def _lock_accounts_by_id(account_ids: list) -> dict:
    """Lock Account rows in stable UUID order; return {pk: account} dict."""
    sorted_ids = sorted(str(pk) for pk in account_ids)
    qs = Account.objects.select_for_update().filter(pk__in=sorted_ids).order_by("id")
    accounts = {acc.pk: acc for acc in qs}
    for aid in sorted_ids:
        if aid not in {str(k) for k in accounts}:
            raise ServiceError(f"Account {aid} not found.")
    return accounts


def _check_date_open(date, settings: LedgerSettings):
    if settings.locked_through and date <= settings.locked_through:
        raise ServiceError(
            f"Entry date {date} is on or before the posting lock date "
            f"{settings.locked_through}. Choose a later date or ask Admin to "
            "lower the lock date."
        )


def _check_account_postable(account: Account, actor):
    from .policies import can_post_to_account
    if account.is_group:
        raise ServiceError(f"Account '{account}' is a group and cannot receive postings.")
    if not account.is_active:
        raise ServiceError(f"Account '{account}' is inactive.")
    if not can_post_to_account(actor, account):
        raise AuthorizationError(f"You do not have posting rights on account '{account}'.")


def _build_lines(entry: JournalEntry, line_specs: list[dict], accounts: dict):
    """
    Delete existing draft lines and create new ones.
    line_specs: list of {'account_id': UUID, 'debit': Decimal, 'credit': Decimal}
    """
    entry.lines.all().delete()
    for i, spec in enumerate(line_specs, start=1):
        debit, credit = _validate_line_amounts(
            spec.get("debit", ZERO), spec.get("credit", ZERO)
        )
        account_id = str(spec["account_id"])
        account = accounts.get(account_id) or accounts.get(
            next((k for k in accounts if str(k) == account_id), None)
        )
        JournalLine.objects.create(
            entry=entry,
            line_number=i,
            account=account,
            debit=debit,
            credit=credit,
        )


def _validate_balanced(lines_qs):
    """Check that the entry is balanced and has >= 2 lines."""
    lines = list(lines_qs)
    if len(lines) < 2:
        raise ServiceError("A journal entry requires at least two lines.")
    total_debit = sum(l.debit for l in lines)
    total_credit = sum(l.credit for l in lines)
    if total_debit != total_credit:
        raise ServiceError(
            f"Journal is not balanced: debits {total_debit}, credits {total_credit}."
        )
    if total_debit == ZERO:
        raise ServiceError("Journal total must be greater than zero.")


def _record_activity(actor, action: str, object_type: str, object_id: str, metadata: dict | None = None):
    ActivityRecord.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Draft management
# ---------------------------------------------------------------------------

def create_draft(
    actor,
    date,
    narration: str,
    kind: str,
    line_specs: list[dict],
    *,
    replacement_of: JournalEntry | None = None,
) -> JournalEntry:
    """
    Create a new DRAFT journal entry.  Lines are validated for format only;
    balance is not required in a draft.  Returns the saved draft.
    """
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise AuthorizationError("You must be logged in to create a draft.")

    with transaction.atomic():
        _lock_settings()
        account_ids = [spec["account_id"] for spec in line_specs]
        accounts = _lock_accounts_by_id(account_ids) if account_ids else {}

        entry = JournalEntry.objects.create(
            creator=actor,
            date=date,
            narration=narration,
            kind=kind,
            state=EntryState.DRAFT,
            version=1,
            replacement_of=replacement_of,
        )
        if line_specs:
            _build_lines(entry, line_specs, accounts)

        _record_activity(actor, "CREATE_DRAFT", "JournalEntry", entry.pk,
                         {"kind": kind, "replacement_of": str(replacement_of.pk) if replacement_of else None})
        logger.info("Draft created: %s by %s", entry.pk, actor.username)
        return entry


def update_draft(
    actor,
    entry: JournalEntry,
    submitted_version: int,
    date,
    narration: str,
    kind: str,
    line_specs: list[dict],
) -> JournalEntry:
    """
    Update an existing DRAFT.  Raises StaleVersionError if the submitted
    version does not match.
    """
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise AuthorizationError("You must be logged in.")

    with transaction.atomic():
        _lock_settings()
        account_ids = [spec["account_id"] for spec in line_specs]
        accounts = _lock_accounts_by_id(account_ids) if account_ids else {}
        locked_entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)

        if locked_entry.state != EntryState.DRAFT:
            raise ServiceError("Only draft entries can be edited.")
        if locked_entry.version != submitted_version:
            raise StaleVersionError(
                "This draft was modified by another session. Reload and try again."
            )

        from .policies import can_edit_draft
        if not can_edit_draft(actor, locked_entry):
            raise AuthorizationError("You cannot edit this draft.")

        locked_entry.date = date
        locked_entry.narration = narration
        locked_entry.kind = kind
        locked_entry.version += 1
        locked_entry.save(update_fields=["date", "narration", "kind", "version"])

        if line_specs:
            _build_lines(locked_entry, line_specs, accounts)
        else:
            locked_entry.lines.all().delete()

        _record_activity(actor, "UPDATE_DRAFT", "JournalEntry", locked_entry.pk)
        logger.info("Draft updated: %s by %s", locked_entry.pk, actor.username)
        return locked_entry


def delete_draft(actor, entry: JournalEntry) -> None:
    """Delete a draft entry and its lines."""
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise AuthorizationError("You must be logged in.")

    with transaction.atomic():
        _lock_settings()
        locked_entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)

        if locked_entry.state != EntryState.DRAFT:
            raise ServiceError("Only draft entries can be deleted.")

        from .policies import can_edit_draft
        if not can_edit_draft(actor, locked_entry):
            raise AuthorizationError("You cannot delete this draft.")

        entry_id = str(locked_entry.pk)
        locked_entry.lines.all().delete()
        locked_entry.delete()

        _record_activity(actor, "DELETE_DRAFT", "JournalEntry", entry_id)
        logger.info("Draft deleted: %s by %s", entry_id, actor.username)


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def post_entry(
    actor,
    entry: JournalEntry,
    submitted_version: int,
    idempotency_key,
    *,
    date=None,
    narration: str | None = None,
) -> JournalEntry:
    """
    Post an existing DRAFT entry.

    The idempotency_key is a UUID supplied by the caller (typically generated
    once per form render and stored in a hidden field).  Retrying with the
    same key and identical payload returns the originally posted entry.
    Retrying with the same key but a different payload raises ConflictError.

    date and narration may be supplied to override the draft values at
    the moment of posting (for simple entry forms that embed date/narration
    without a separate draft-edit step).
    """
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise AuthorizationError("You must be logged in.")

    with transaction.atomic():
        settings = _lock_settings()
        actor = User.objects.get(pk=actor.pk)
        if not actor.is_active:
            raise AuthorizationError("Actor is inactive.")

        # ── Idempotency check first ──────────────────────────────────────
        # We need the payload hash. To do that, read the draft's current
        # state (without locking yet) to compute the hash, then do the
        # actual locked work if we are the first caller.
        #
        # For the idempotency INSERT we use a savepoint so that a
        # duplicate-key error does not abort the outer atomic block.
        try:
            preview = JournalEntry.objects.get(pk=entry.pk)
        except JournalEntry.DoesNotExist:
            raise ServiceError("Entry not found.")

        # Apply optional overrides to the preview to compute the hash.
        preview_date = date if date is not None else preview.date
        preview_narration = narration if narration is not None else preview.narration

        line_specs = [
            {"account_id": str(ln.account_id), "debit": ln.debit, "credit": ln.credit}
            for ln in preview.lines.all()
        ]
        p_hash = _payload_hash(preview_date, preview_narration, preview.kind, line_specs)

        # Try to create the idempotency record inside a savepoint.
        existing_req = None
        try:
            with transaction.atomic():
                req = PostingRequest.objects.create(
                    actor=actor,
                    operation="POST",
                    key=idempotency_key,
                    payload_hash=p_hash,
                    result=preview,  # temporary; updated after commit below
                )
        except IntegrityError:
            existing_req = PostingRequest.objects.get(
                actor=actor, operation="POST", key=idempotency_key
            )
            if existing_req.payload_hash != p_hash:
                raise ConflictError(
                    "This idempotency key was already used with a different payload."
                )
            return existing_req.result  # Already posted; return original result.

        # ── Normal posting path ──────────────────────────────────────────
        locked_entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
        if locked_entry.state != EntryState.DRAFT:
            raise ServiceError("Only draft entries can be posted.")
        if locked_entry.version != submitted_version:
            raise StaleVersionError(
                "This draft was modified. Reload and confirm before posting."
            )

        # Apply optional overrides.
        if date is not None:
            locked_entry.date = date
        if narration is not None:
            locked_entry.narration = narration

        # Lock accounts in stable order.
        account_ids = [spec["account_id"] for spec in line_specs]
        accounts = _lock_accounts_by_id(account_ids)

        # Reload permissions and account state after acquiring locks.
        posting_date = locked_entry.date
        _check_date_open(posting_date, settings)

        for account_id, account in accounts.items():
            _check_account_postable(account, actor)

        # Validate balance and minimum lines.
        lines = locked_entry.lines.all()
        _validate_balanced(lines)

        # Assign posting number via sequence (gap-tolerant; never MAX+1).
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval('accounting_posting_number_seq')")
            posting_number = cursor.fetchone()[0]

        # Freeze the entry.
        now = timezone.now()
        locked_entry.state = EntryState.POSTED
        locked_entry.posted_at = now
        locked_entry.posting_number = posting_number
        locked_entry.save(update_fields=["state", "posted_at", "posting_number",
                                          "date", "narration", "version"])

        # Update the idempotency request to point to the committed entry.
        req.result = locked_entry
        req.save(update_fields=["result"])

        _record_activity(actor, "POST_ENTRY", "JournalEntry", locked_entry.pk,
                         {"posting_number": posting_number, "kind": locked_entry.kind})
        logger.info("Entry posted: %s (posting #%s) by %s",
                    locked_entry.pk, posting_number, actor.username)
        return locked_entry


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------

def reverse_entry(
    actor,
    original: JournalEntry,
    reversal_date,
    narration: str,
    idempotency_key,
) -> JournalEntry:
    """
    Create and immediately post a full reversal of a POSTED entry.

    Debit and credit amounts on every line are swapped.  The reversal is
    linked to the original via reversal_of.  Only one direct full reversal
    is permitted per original in this POC.
    """
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise AuthorizationError("You must be logged in.")

    with transaction.atomic():
        settings = _lock_settings()
        actor = User.objects.get(pk=actor.pk)
        if not actor.is_active:
            raise AuthorizationError("Actor is inactive.")

        locked_original = JournalEntry.objects.select_for_update().get(pk=original.pk)
        if locked_original.state != EntryState.POSTED:
            raise ServiceError("Only posted entries can be reversed.")

        if locked_original.kind == EntryKind.REVERSAL or locked_original.reversal_of_id is not None:
            raise ServiceError("A reversal entry cannot itself be reversed.")

        # Guard: only one full reversal allowed.
        if JournalEntry.objects.filter(reversal_of=locked_original).exists():
            raise ServiceError("This entry has already been reversed.")

        from .policies import can_reverse_entry
        if not can_reverse_entry(actor, locked_original):
            raise AuthorizationError("You do not have permission to reverse this entry.")

        orig_lines = list(locked_original.lines.select_related("account").all())
        account_ids = [str(ln.account_id) for ln in orig_lines]
        accounts = _lock_accounts_by_id(account_ids)

        _check_date_open(reversal_date, settings)
        for account in accounts.values():
            _check_account_postable(account, actor)

        # Build reversal payload for idempotency hash.
        reversal_line_specs = [
            {"account_id": str(ln.account_id), "debit": ln.credit, "credit": ln.debit}
            for ln in orig_lines
        ]
        p_hash = _payload_hash(reversal_date, narration, EntryKind.REVERSAL, reversal_line_specs)

        # Create the reversal draft and idempotency record inside a savepoint.
        placeholder_entry = JournalEntry.objects.create(
            creator=actor,
            date=reversal_date,
            narration=narration,
            kind=EntryKind.REVERSAL,
            state=EntryState.DRAFT,
            version=1,
        )
        try:
            with transaction.atomic():
                req = PostingRequest.objects.create(
                    actor=actor,
                    operation="REVERSE",
                    key=idempotency_key,
                    payload_hash=p_hash,
                    result=placeholder_entry,
                )
        except IntegrityError:
            # Clean up the draft we just created since we won't use it.
            placeholder_entry.delete()
            existing = PostingRequest.objects.get(
                actor=actor, operation="REVERSE", key=idempotency_key
            )
            if existing.payload_hash != p_hash:
                raise ConflictError("Idempotency key conflict on reversal.")
            return existing.result

        # Create swapped lines.
        for i, ln in enumerate(orig_lines, start=1):
            JournalLine.objects.create(
                entry=placeholder_entry,
                line_number=i,
                account=ln.account,
                debit=ln.credit,
                credit=ln.debit,
            )

        # Post the reversal entry.
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval('accounting_posting_number_seq')")
            posting_number = cursor.fetchone()[0]

        now = timezone.now()
        placeholder_entry.state = EntryState.POSTED
        placeholder_entry.posted_at = now
        placeholder_entry.posting_number = posting_number
        placeholder_entry.reversal_of = locked_original
        placeholder_entry.save(update_fields=[
            "state", "posted_at", "posting_number", "reversal_of", "version"
        ])

        req.result = placeholder_entry
        req.save(update_fields=["result"])

        _record_activity(actor, "REVERSE_ENTRY", "JournalEntry", placeholder_entry.pk,
                         {"original": str(locked_original.pk),
                          "posting_number": posting_number})
        logger.info("Reversal posted: %s reverses %s (posting #%s) by %s",
                    placeholder_entry.pk, locked_original.pk, posting_number, actor.username)
        return placeholder_entry


# ---------------------------------------------------------------------------
# Lock date management
# ---------------------------------------------------------------------------

def set_posting_lock_date(actor, new_date, reason: str) -> LedgerSettings:
    """
    Admin-only.  Set or lower the posting lock date.
    Serialised with all posting operations via the LedgerSettings lock.
    """
    if not is_admin(actor):
        raise AuthorizationError("Only Admins can change the posting lock date.")
    if not reason or not reason.strip():
        raise ServiceError("A reason is required when changing the posting lock date.")

    with transaction.atomic():
        settings = _lock_settings()
        old_date = settings.locked_through
        settings.locked_through = new_date
        settings.save(update_fields=["locked_through"])

        _record_activity(actor, "SET_LOCK_DATE", "LedgerSettings", "1",
                         {"old_date": str(old_date), "new_date": str(new_date),
                          "reason": reason})
        logger.info("Lock date changed from %s to %s by %s (reason: %s)",
                    old_date, new_date, actor.username, reason)
        return settings


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------

def create_account(actor, **kwargs: Any) -> Account:
    """Admin-only.  Create a new Account after full_clean validation."""
    if not is_admin(actor):
        raise AuthorizationError("Only Admins can create accounts.")

    with transaction.atomic():
        _lock_settings()
        account = Account(**kwargs)
        account.full_clean()
        account.save()
        _record_activity(actor, "CREATE_ACCOUNT", "Account", account.pk,
                         {"code": account.code})
        logger.info("Account created: %s by %s", account.pk, actor.username)
        return account


def update_account(actor, account: Account, **kwargs: Any) -> Account:
    """
    Admin-only.  Update an account.  Raises ServiceError if the account is
    used (has lines) and the caller attempts to change a frozen field.
    """
    if not is_admin(actor):
        raise AuthorizationError("Only Admins can update accounts.")

    FROZEN_ON_USE = {"classical_type", "reporting_class", "purpose", "normal_side", "parent"}

    with transaction.atomic():
        _lock_settings()
        locked = Account.objects.select_for_update().get(pk=account.pk)
        is_used = locked.lines.exists()

        for field, value in kwargs.items():
            if is_used and field in FROZEN_ON_USE and getattr(locked, field) != value:
                raise ServiceError(
                    f"Cannot change '{field}' on an account that has been used in "
                    "journal entries (D04)."
                )
            setattr(locked, field, value)

        locked.full_clean()
        locked.save()
        _record_activity(actor, "UPDATE_ACCOUNT", "Account", locked.pk,
                         {"fields": list(kwargs.keys())})
        return locked


def deactivate_account(actor, account: Account) -> Account:
    """Admin-only.  Deactivate an account; it can no longer receive new postings."""
    if not is_admin(actor):
        raise AuthorizationError("Only Admins can deactivate accounts.")

    with transaction.atomic():
        settings = _lock_settings()
        locked = Account.objects.select_for_update().get(pk=account.pk)
        if not locked.is_active:
            raise ServiceError("Account is already inactive.")
        if settings.opening_equity_id == locked.pk:
            raise ServiceError("Cannot deactivate the configured opening equity account.")
        locked.is_active = False
        locked.save(update_fields=["is_active"])
        _record_activity(actor, "DEACTIVATE_ACCOUNT", "Account", locked.pk)
        logger.info("Account deactivated: %s by %s", locked.pk, actor.username)
        return locked


def delete_account(actor, account: Account) -> None:
    """
    Admin-only. Delete an unused account (D08).
    Rejects accounts with journal lines, child accounts, or configured opening equity.
    """
    if not is_admin(actor):
        raise AuthorizationError("Only Admins can delete accounts.")

    with transaction.atomic():
        settings = _lock_settings()
        locked = Account.objects.select_for_update().get(pk=account.pk)
        if locked.lines.exists():
            raise ServiceError("Cannot delete an account that has been used in journal entries.")
        if settings.opening_equity_id == locked.pk:
            raise ServiceError("Cannot delete the configured opening equity account.")
        if locked.children.exists():
            raise ServiceError("Cannot delete an account that has child accounts.")
        account_id = str(locked.pk)
        code = locked.code
        locked.delete()
        _record_activity(actor, "DELETE_ACCOUNT", "Account", account_id, {"code": code})
        logger.info("Account deleted: %s (%s) by %s", account_id, code, actor.username)


def set_account_grants(actor, account: Account, grants_data: list[dict[str, Any]]) -> list[AccountGrant]:
    """
    Admin-only. Update view/post grants for an account across specified users.
    grants_data: list of dicts with keys: 'user' (User instance), 'can_view' (bool), 'can_post' (bool).
    Enforces check constraint: can_post => can_view.
    """
    if not is_admin(actor):
        raise AuthorizationError("Only Admins can manage account grants.")

    with transaction.atomic():
        _lock_settings()
        locked_account = Account.objects.select_for_update().get(pk=account.pk)
        result_grants = []
        activity_grants = []

        for item in grants_data:
            target_user = item["user"]
            can_view = bool(item.get("can_view", False))
            can_post = bool(item.get("can_post", False))
            if can_post and not can_view:
                can_view = True

            grant, _ = AccountGrant.objects.update_or_create(
                account=locked_account,
                user=target_user,
                defaults={"can_view": can_view, "can_post": can_post},
            )
            result_grants.append(grant)
            activity_grants.append({
                "username": target_user.username,
                "can_view": can_view,
                "can_post": can_post,
            })

        _record_activity(
            actor,
            "UPDATE_ACCOUNT_GRANTS",
            "Account",
            locked_account.pk,
            {"code": locked_account.code, "grants": activity_grants},
        )
        logger.info("Updated grants for account %s by %s", locked_account.code, actor.username)
        return result_grants


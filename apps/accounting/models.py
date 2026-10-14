import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .choices import ClassicalType, EntryKind, EntryState, Purpose, ReportingClass, Side, Visibility


class Account(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=160)
    classical_type = models.CharField(max_length=10, choices=ClassicalType.choices)
    reporting_class = models.CharField(max_length=10, choices=ReportingClass.choices)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.GENERAL)
    normal_side = models.CharField(max_length=6, choices=Side.choices)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    is_group = models.BooleanField(default=False)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.SHARED)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(visibility="SHARED", owner__isnull=True) | Q(visibility="PERSONAL", owner__isnull=False)),
                name="account_visibility_owner",
            ),
            models.CheckConstraint(condition=Q(classical_type__in=ClassicalType.values), name="account_classical_valid"),
            models.CheckConstraint(condition=Q(reporting_class__in=ReportingClass.values), name="account_reporting_valid"),
            models.CheckConstraint(condition=Q(purpose__in=Purpose.values), name="account_purpose_valid"),
            models.CheckConstraint(condition=Q(normal_side__in=Side.values), name="account_side_valid"),
            models.CheckConstraint(condition=~Q(id=models.F("parent_id")), name="account_not_self_parent"),
        ]

    def clean(self):
        super().clean()
        if (self.visibility == Visibility.PERSONAL) != bool(self.owner_id):
            raise ValidationError("A personal account needs one owner; a shared account has no owner.")
        expected_class = {
            Purpose.CASH: ReportingClass.ASSET, Purpose.BANK: ReportingClass.ASSET,
            Purpose.INVENTORY: ReportingClass.ASSET, Purpose.MEMBER_CAPITAL: ReportingClass.EQUITY,
            Purpose.MEMBER_DRAWINGS: ReportingClass.EQUITY, Purpose.OPENING_EQUITY: ReportingClass.EQUITY,
        }.get(self.purpose)
        if expected_class and self.reporting_class != expected_class:
            raise ValidationError("Account purpose and reporting class disagree.")
        if (self.classical_type == ClassicalType.NOMINAL) != (
            self.reporting_class in (ReportingClass.INCOME, ReportingClass.EXPENSE)
        ):
            raise ValidationError("Nominal accounts must report as income or expense.")
        seen = {self.pk}
        parent = self.parent if self.parent_id else None
        while parent:
            if parent.pk in seen:
                raise ValidationError("Account groups cannot contain cycles.")
            seen.add(parent.pk)
            if not parent.is_group or parent.reporting_class != self.reporting_class:
                raise ValidationError("Parent must be a group in the same reporting class.")
            parent = parent.parent

    def __str__(self):
        return f"{self.code} — {self.name}"


class LedgerSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=120, default="Household Ledger")
    currency = models.CharField(max_length=3, default="INR", editable=False)
    timezone_name = models.CharField(max_length=40, default="Asia/Kolkata", editable=False)
    fiscal_start_month = models.PositiveSmallIntegerField(default=4, editable=False)
    fiscal_start_day = models.PositiveSmallIntegerField(default=1, editable=False)
    locked_through = models.DateField(null=True, blank=True)
    opening_equity = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        verbose_name_plural = "ledger settings"
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="ledger_singleton"),
            models.CheckConstraint(condition=Q(currency="INR"), name="ledger_inr"),
            models.CheckConstraint(condition=Q(fiscal_start_month=4, fiscal_start_day=1), name="ledger_indian_fy"),
            models.CheckConstraint(condition=Q(timezone_name="Asia/Kolkata"), name="ledger_timezone"),
        ]


class AccountGrant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="account_grants")
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="grants")
    can_view = models.BooleanField(default=True)
    can_post = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "account"], name="unique_account_grant"),
            models.CheckConstraint(condition=Q(can_post=False) | Q(can_view=True), name="posting_requires_view"),
        ]


class JournalEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField(default=timezone.localdate)
    narration = models.TextField(blank=True, max_length=2000)
    kind = models.CharField(max_length=10, choices=EntryKind.choices, default=EntryKind.JOURNAL)
    state = models.CharField(max_length=6, choices=EntryState.choices, default=EntryState.DRAFT)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    posting_number = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    reversal_of = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal")
    replacement_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacements")

    class Meta:
        ordering = ["date", "posting_number", "id"]
        indexes = [models.Index(fields=["state", "date"], name="entry_state_date_idx")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(state="DRAFT", posted_at__isnull=True, posting_number__isnull=True, reversal_of__isnull=True)
                    | Q(state="POSTED", posted_at__isnull=False, posting_number__isnull=False)
                ), name="entry_state_consistency",
            ),
            models.CheckConstraint(condition=Q(kind__in=EntryKind.values), name="entry_kind_valid"),
            models.CheckConstraint(condition=Q(version__gte=1), name="entry_version_positive"),
            models.CheckConstraint(condition=~Q(id=models.F("reversal_of_id")), name="entry_not_own_reversal"),
        ]


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    line_number = models.PositiveSmallIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["line_number"]
        indexes = [
            models.Index(fields=["entry"], name="journalline_entry_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["entry", "line_number"], name="unique_entry_line"),
            models.CheckConstraint(condition=Q(line_number__gte=1), name="line_number_positive"),
            models.CheckConstraint(
                condition=(
                    Q(debit__gt=0, debit__lte=Decimal("9999999999999999.99"), credit=0)
                    | Q(credit__gt=0, credit__lte=Decimal("9999999999999999.99"), debit=0)
                ), name="line_single_positive_side",
            ),
        ]


class PostingRequest(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation = models.CharField(max_length=24)
    key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    result = models.ForeignKey(JournalEntry, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "operation", "key"], name="unique_posting_request")]

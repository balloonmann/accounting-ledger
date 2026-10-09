import uuid
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .choices import ClassicalType, EntryKind, Purpose, ReportingClass, Side, Visibility
from .models import Account, JournalEntry, LedgerSettings
from .policies import postable_accounts, visible_accounts

User = get_user_model()


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            "code",
            "name",
            "classical_type",
            "reporting_class",
            "purpose",
            "normal_side",
            "parent",
            "is_group",
            "visibility",
            "owner",
            "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "e.g. 1010", "class": "form-control"}),
            "name": forms.TextInput(attrs={"placeholder": "Account name", "class": "form-control"}),
            "classical_type": forms.Select(attrs={"class": "form-control"}),
            "reporting_class": forms.Select(attrs={"class": "form-control"}),
            "purpose": forms.Select(attrs={"class": "form-control"}),
            "normal_side": forms.Select(attrs={"class": "form-control"}),
            "parent": forms.Select(attrs={"class": "form-control"}),
            "visibility": forms.Select(attrs={"class": "form-control"}),
            "owner": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Account.objects.filter(is_group=True)
        self.fields["owner"].queryset = User.objects.filter(is_active=True)
        self.fields["parent"].required = False
        self.fields["owner"].required = False

        if self.instance and self.instance.pk:
            # Exclude self from parent choices to avoid self-parenting
            self.fields["parent"].queryset = self.fields["parent"].queryset.exclude(pk=self.instance.pk)
            # If account has lines, freeze fields per D04
            if self.instance.lines.exists():
                for field_name in ["classical_type", "reporting_class", "purpose", "normal_side", "parent"]:
                    self.fields[field_name].disabled = True
                    self.fields[field_name].help_text = "Frozen because this account has recorded journal lines (D04)."

    def clean(self):
        cleaned_data = super().clean()
        visibility = cleaned_data.get("visibility")
        owner = cleaned_data.get("owner")
        if visibility == Visibility.PERSONAL and not owner:
            self.add_error("owner", "A personal account requires an owner.")
        elif visibility == Visibility.SHARED and owner:
            cleaned_data["owner"] = None
        return cleaned_data


class ExpenseEntryForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    narration = forms.CharField(max_length=2000, widget=forms.TextInput(attrs={"placeholder": "What was this expense for?", "class": "form-control"}))
    source_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Paid From",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    expense_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Expense Category",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00", "class": "form-control"}),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput(), initial=uuid.uuid4)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            postable = postable_accounts(user)
            self.fields["source_account"].queryset = postable.filter(reporting_class=ReportingClass.ASSET)
            self.fields["expense_account"].queryset = postable.filter(reporting_class=ReportingClass.EXPENSE)


class IncomeEntryForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    narration = forms.CharField(max_length=2000, widget=forms.TextInput(attrs={"placeholder": "What was this income for?", "class": "form-control"}))
    destination_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Received Into",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    income_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Income Category",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00", "class": "form-control"}),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput(), initial=uuid.uuid4)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            postable = postable_accounts(user)
            self.fields["destination_account"].queryset = postable.filter(reporting_class=ReportingClass.ASSET)
            self.fields["income_account"].queryset = postable.filter(reporting_class=ReportingClass.INCOME)


class TransferEntryForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    narration = forms.CharField(max_length=2000, widget=forms.TextInput(attrs={"placeholder": "Reason for transfer", "class": "form-control"}))
    from_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Transfer From",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    to_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Transfer To",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00", "class": "form-control"}),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput(), initial=uuid.uuid4)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            postable = postable_accounts(user).filter(reporting_class=ReportingClass.ASSET)
            self.fields["from_account"].queryset = postable
            self.fields["to_account"].queryset = postable

    def clean(self):
        cleaned_data = super().clean()
        from_acc = cleaned_data.get("from_account")
        to_acc = cleaned_data.get("to_account")
        if from_acc and to_acc and from_acc == to_acc:
            self.add_error("to_account", "Transfer source and destination must be different accounts.")
        return cleaned_data


class OpeningBalanceForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    narration = forms.CharField(max_length=2000, widget=forms.TextInput(attrs={"placeholder": "Opening balance note", "class": "form-control"}))
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Account",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    side = forms.ChoiceField(
        choices=Side.choices,
        label="Normal Balance Side",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00", "class": "form-control"}),
    )
    offset_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label="Offset Account (Equity)",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput(), initial=uuid.uuid4)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            postable = postable_accounts(user)
            self.fields["account"].queryset = postable.exclude(purpose=Purpose.OPENING_EQUITY)
            self.fields["offset_account"].queryset = postable.filter(reporting_class=ReportingClass.EQUITY)
            settings = LedgerSettings.objects.first()
            if settings and settings.opening_equity:
                self.fields["offset_account"].initial = settings.opening_equity


class ReversalForm(forms.Form):
    reversal_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    narration = forms.CharField(max_length=2000, widget=forms.TextInput(attrs={"placeholder": "Reason for reversal", "class": "form-control"}))
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput(), initial=uuid.uuid4)


class JournalHeaderForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    narration = forms.CharField(max_length=2000, widget=forms.TextInput(attrs={"placeholder": "Journal narration / description", "class": "form-control"}))
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput(), initial=uuid.uuid4)
    version = forms.IntegerField(widget=forms.HiddenInput(), required=False, initial=1)


class LockDateForm(forms.Form):
    locked_through = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Transactions on or before this date cannot be posted or reversed.",
    )
    clear_lock = forms.BooleanField(
        required=False,
        label="Clear lock completely (allow posting to all dates)",
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 2,
            "class": "form-control",
            "placeholder": "Explain why this lock date is being established or changed (required).",
        }),
        help_text="Reason is recorded in the activity log.",
    )

    def clean(self):
        cleaned_data = super().clean()
        clear_lock = cleaned_data.get("clear_lock")
        locked_through = cleaned_data.get("locked_through")
        if not clear_lock and not locked_through:
            self.add_error("locked_through", "Specify a lock date or check 'Clear lock completely'.")
        return cleaned_data

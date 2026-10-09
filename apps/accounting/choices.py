from django.db import models


class ClassicalType(models.TextChoices):
    PERSONAL = "PERSONAL", "Personal"
    REAL = "REAL", "Real"
    NOMINAL = "NOMINAL", "Nominal"


class ReportingClass(models.TextChoices):
    ASSET = "ASSET", "Asset"
    LIABILITY = "LIABILITY", "Liability"
    EQUITY = "EQUITY", "Equity"
    INCOME = "INCOME", "Income"
    EXPENSE = "EXPENSE", "Expense"


class Purpose(models.TextChoices):
    GENERAL = "GENERAL", "General"
    CASH = "CASH", "Cash"
    BANK = "BANK", "Bank"
    INVENTORY = "INVENTORY", "Inventory"
    MEMBER_CAPITAL = "MEMBER_CAPITAL", "Member capital"
    MEMBER_DRAWINGS = "MEMBER_DRAWINGS", "Member drawings"
    OPENING_EQUITY = "OPENING_EQUITY", "Opening equity"


class Side(models.TextChoices):
    DEBIT = "DEBIT", "Debit"
    CREDIT = "CREDIT", "Credit"


class Visibility(models.TextChoices):
    SHARED = "SHARED", "Shared"
    PERSONAL = "PERSONAL", "Personal to member"


class EntryKind(models.TextChoices):
    JOURNAL = "JOURNAL", "Journal"
    INCOME = "INCOME", "Income"
    EXPENSE = "EXPENSE", "Expense"
    TRANSFER = "TRANSFER", "Transfer"
    OPENING = "OPENING", "Opening"
    REVERSAL = "REVERSAL", "Reversal"


class EntryState(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    POSTED = "POSTED", "Posted"

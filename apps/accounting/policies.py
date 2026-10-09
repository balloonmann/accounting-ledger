from django.db.models import Q
from apps.identity.policies import is_admin
from .models import Account


def visible_accounts(user):
    if not user or not user.is_authenticated or not user.is_active:
        return Account.objects.none()
    if is_admin(user):
        return Account.objects.all()
    return Account.objects.filter(
        Q(visibility="SHARED") | Q(owner=user) | Q(grants__user=user, grants__can_view=True)
    ).distinct()


def postable_accounts(user):
    if not user or not user.is_authenticated or not user.is_active:
        return Account.objects.none()
    accounts = Account.objects.filter(is_active=True, is_group=False)
    if is_admin(user):
        return accounts
    return accounts.filter(Q(owner=user) | Q(grants__user=user, grants__can_post=True, grants__can_view=True)).distinct()


def can_view_account(user, account):
    return visible_accounts(user).filter(pk=account.pk).exists()


def can_post_to_account(user, account):
    return postable_accounts(user).filter(pk=account.pk).exists()


def can_view_entry(user, entry):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if not entry.lines.exists():
        return is_admin(user) or entry.creator_id == user.pk
    return not entry.lines.exclude(account__in=visible_accounts(user)).exists()


def can_edit_draft(user, entry):
    return (
        entry.state == "DRAFT" and can_view_entry(user, entry)
        and (is_admin(user) or entry.creator_id == user.pk)
        and not entry.lines.exclude(account__in=postable_accounts(user)).exists()
    )


def can_reverse_entry(user, entry):
    return (
        entry.state == "POSTED" and can_view_entry(user, entry)
        and (is_admin(user) or entry.creator_id == user.pk)
        and not entry.lines.exclude(account__in=postable_accounts(user)).exists()
    )

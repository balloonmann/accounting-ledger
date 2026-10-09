from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/new/", views.account_create, name="account_create"),
    path("accounts/<uuid:pk>/edit/", views.account_edit, name="account_edit"),
    path("accounts/<uuid:pk>/deactivate/", views.account_deactivate, name="account_deactivate"),
    path("accounts/<uuid:pk>/ledger/", views.account_ledger, name="account_ledger"),
    path("accounts/<uuid:pk>/grants/", views.account_grants, name="account_grants"),
    path("settings/lock-date/", views.settings_lock_date, name="settings_lock_date"),
    path("entries/", views.entry_list, name="entry_list"),
    path("entries/<uuid:pk>/", views.entry_detail, name="entry_detail"),
    path("entries/<uuid:pk>/reverse/", views.entry_reverse, name="entry_reverse"),
    path("entries/<uuid:pk>/replace/", views.entry_replace, name="entry_replace"),
    path("entries/new/expense/", views.entry_expense, name="entry_expense"),
    path("entries/new/income/", views.entry_income, name="entry_income"),
    path("entries/new/transfer/", views.entry_transfer, name="entry_transfer"),
    path("entries/new/journal/", views.entry_journal, name="entry_journal"),
    path("entries/new/opening/", views.entry_opening, name="entry_opening"),
    path("drafts/", views.draft_list, name="draft_list"),
    path("drafts/<uuid:pk>/edit/", views.draft_edit, name="draft_edit"),
    path("drafts/<uuid:pk>/delete/", views.draft_delete, name="draft_delete"),
    path("drafts/<uuid:pk>/post/", views.draft_post, name="draft_post"),
]

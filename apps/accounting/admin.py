from django.contrib import admin
from .models import Account, AccountGrant, JournalEntry, JournalLine, LedgerSettings, PostingRequest


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (Account, AccountGrant, JournalEntry, JournalLine, LedgerSettings, PostingRequest):
    admin.site.register(model, ReadOnlyAdmin)

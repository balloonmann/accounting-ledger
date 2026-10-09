from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class LedgerUserAdmin(UserAdmin):
    # Domain administration goes through coordinated services in later milestones.
    fields = None
    fieldsets = UserAdmin.fieldsets + (("Household", {"fields": ("role",)}),)
    readonly_fields = tuple(field.name for field in User._meta.fields if field.name != "id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

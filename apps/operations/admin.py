from django.contrib import admin
from apps.accounting.admin import ReadOnlyAdmin
from .models import ActivityRecord

admin.site.register(ActivityRecord, ReadOnlyAdmin)

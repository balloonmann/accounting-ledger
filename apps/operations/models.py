from django.conf import settings
from django.db import models


class ActivityRecord(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

"""
Migration 0006: Add explicit index on JournalLine.entry.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0005_freeze_narration"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="journalline",
            index=models.Index(fields=["entry"], name="journalline_entry_idx"),
        ),
    ]

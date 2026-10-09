from django.db import migrations


def initialize_book(apps, schema_editor):
    Settings = apps.get_model("accounting", "LedgerSettings")
    Settings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("accounting", "0002_initial")]
    operations = [migrations.RunPython(initialize_book, migrations.RunPython.noop)]

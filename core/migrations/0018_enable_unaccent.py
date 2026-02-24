from django.db import connection, migrations


def enable_unaccent(apps, schema_editor):
    if connection.vendor == "postgresql":
        schema_editor.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")


def disable_unaccent(apps, schema_editor):
    if connection.vendor == "postgresql":
        schema_editor.execute("DROP EXTENSION IF EXISTS unaccent;")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_profile_last_session_key"),
    ]

    operations = [
        migrations.RunPython(enable_unaccent, disable_unaccent),
    ]

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0017_profile_last_session_key'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS unaccent;",
            reverse_sql="DROP EXTENSION IF EXISTS unaccent;",
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_candidate_last_ready_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidate',
            name='technologies',
            field=models.TextField(blank=True),
        ),
    ]

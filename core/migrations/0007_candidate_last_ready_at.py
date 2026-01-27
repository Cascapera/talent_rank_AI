from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_candidatejob_and_candidate_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidate',
            name='ready_at',
            field=models.DateField(blank=True, null=True),
        ),
    ]

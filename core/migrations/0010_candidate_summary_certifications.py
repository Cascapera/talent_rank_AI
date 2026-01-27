from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_candidate_languages'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidate',
            name='summary',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='certifications',
            field=models.TextField(blank=True),
        ),
    ]

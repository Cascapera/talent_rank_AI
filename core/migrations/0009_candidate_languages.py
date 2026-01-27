from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_candidate_technologies'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidate',
            name='languages',
            field=models.TextField(blank=True),
        ),
    ]

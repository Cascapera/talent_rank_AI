from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0014_backfill_job_candidate_user'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='user',
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name='jobs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='user',
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name='candidates',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name='candidate',
            constraint=models.UniqueConstraint(
                fields=('user', 'linkedin_url'),
                name='core_candidate_user_linkedin_unique',
            ),
        ),
    ]

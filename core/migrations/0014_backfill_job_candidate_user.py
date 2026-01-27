from django.conf import settings
from django.db import migrations


def backfill_user(apps, schema_editor):
    Job = apps.get_model('core', 'Job')
    Candidate = apps.get_model('core', 'Candidate')
    User = apps.get_model(settings.AUTH_USER_MODEL)
    first_user = User.objects.order_by('id').first()
    if not first_user:
        return
    Job.objects.filter(user_id__isnull=True).update(user_id=first_user.id)
    Candidate.objects.filter(user_id__isnull=True).update(user_id=first_user.id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0013_job_candidate_user'),
    ]

    operations = [
        migrations.RunPython(backfill_user, noop),
    ]

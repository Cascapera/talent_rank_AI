from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_candidate_summary_certifications'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidatejob',
            name='adherence_score',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='candidatejob',
            name='technical_justification',
            field=models.TextField(blank=True),
        ),
    ]

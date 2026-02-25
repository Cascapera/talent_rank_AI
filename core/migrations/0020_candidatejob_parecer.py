from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_add_candidate_resume_pdf"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidatejob",
            name="parecer",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="candidatejob",
            name="parecer_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("NONE", "Sem parecer"),
                    ("RESUMIDO", "Resumido"),
                    ("COMPLETO", "Completo"),
                    ("ROBUSTO", "Robusto"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]

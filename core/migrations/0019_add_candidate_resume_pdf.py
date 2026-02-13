# Generated manually for resume PDF storage

from django.db import migrations, models
import core.models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_enable_unaccent'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidate',
            name='resume_pdf',
            field=models.FileField(
                blank=True,
                help_text='PDF do currículo do candidato. Usado para avaliação mais precisa quando vinculado a uma vaga.',
                null=True,
                upload_to=core.models.resume_upload_to,
                verbose_name='Currículo PDF',
            ),
        ),
    ]

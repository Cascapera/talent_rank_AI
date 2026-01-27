from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_candidate'),
    ]

    operations = [
        migrations.RenameField(
            model_name='candidate',
            old_name='sent_at',
            new_name='ready_at',
        ),
        migrations.AddField(
            model_name='candidate',
            name='pipeline_status',
            field=models.CharField(blank=True, choices=[('PRIMEIRO_CONTATO', 'Primeiro contato'), ('RESPONDEU', 'Respondeu'), ('ENTREVISTA', 'Entrevista'), ('ENTREVISTA_TECNICA', 'Entrevista tecnica'), ('ENVIADO_GESTOR', 'Enviado para gestor'), ('CANDIDATO_PRONTO', 'Candidato pronto'), ('ENVIADO_CLIENTE', 'Enviado para cliente'), ('CONTRATADO', 'Contratado')], max_length=32),
        ),
    ]

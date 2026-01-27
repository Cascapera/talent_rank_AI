from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_candidate_ready_at_and_status'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='candidate',
            name='pipeline_status',
        ),
        migrations.RemoveField(
            model_name='candidate',
            name='ready_at',
        ),
        migrations.CreateModel(
            name='CandidateJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pipeline_status', models.CharField(blank=True, choices=[('PRIMEIRO_CONTATO', 'Primeiro contato'), ('RESPONDEU', 'Respondeu'), ('ENTREVISTA', 'Entrevista'), ('ENTREVISTA_TECNICA', 'Entrevista tecnica'), ('ENVIADO_GESTOR', 'Enviado para gestor'), ('CANDIDATO_PRONTO', 'Candidato pronto'), ('ENVIADO_CLIENTE', 'Enviado para cliente'), ('CONTRATADO', 'Contratado')], max_length=32)),
                ('ready_at', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('candidate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='job_links', to='core.candidate')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='candidate_links', to='core.job')),
            ],
            options={
                'ordering': ['-updated_at', '-created_at'],
                'unique_together': {('job', 'candidate')},
            },
        ),
    ]

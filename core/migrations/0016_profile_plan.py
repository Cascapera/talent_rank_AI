from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_job_candidate_user_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='plan',
            field=models.CharField(
                choices=[('FREE', 'Free'), ('BASIC', 'Basic'), ('PREMIUM', 'Premium')],
                default='FREE',
                max_length=10,
                verbose_name='Plano',
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='plan_expires_at',
            field=models.DateField(
                blank=True,
                help_text='Quando preenchido, o acesso é bloqueado após esta data. Deixe em branco para plano sem vencimento (manual). Na renovação da assinatura, esta data será atualizada.',
                null=True,
                verbose_name='Vencimento do plano',
            ),
        ),
    ]

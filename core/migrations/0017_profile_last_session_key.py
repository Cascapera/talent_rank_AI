from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0016_profile_plan'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='last_session_key',
            field=models.CharField(blank=True, max_length=40, verbose_name='Ultima sessao ativa'),
        ),
    ]

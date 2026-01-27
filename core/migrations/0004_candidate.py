from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_job_boolean_search'),
    ]

    operations = [
        migrations.CreateModel(
            name='Candidate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160)),
                ('current_title', models.CharField(blank=True, max_length=160)),
                ('current_company', models.CharField(blank=True, max_length=160)),
                ('location', models.CharField(blank=True, max_length=160)),
                ('linkedin_url', models.URLField(max_length=300, unique=True)),
                ('skills', models.TextField(blank=True)),
                ('seniority', models.CharField(blank=True, max_length=80)),
                ('experience_time', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('average_tenure', models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
                ('sent_at', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-updated_at', '-created_at'],
            },
        ),
    ]

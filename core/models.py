import uuid

from django.conf import settings
from django.db import models


def resume_upload_to(instance, filename):
    """Armazena currículos em resumes/{user_id}/{uuid}.pdf"""
    ext = filename.split(".")[-1] if "." in filename else "pdf"
    user_dir = instance.user_id or "shared"
    return f"resumes/{user_dir}/{uuid.uuid4().hex}.{ext}"


class Profile(models.Model):
    """Perfil do usuário: telefone, CPF e plano de assinatura."""
    class Plan(models.TextChoices):
        FREE = 'FREE', 'Free'
        BASIC = 'BASIC', 'Basic'
        PREMIUM = 'PREMIUM', 'Premium'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    phone = models.CharField('Telefone', max_length=20, blank=True)
    cpf = models.CharField('CPF', max_length=14, blank=True)
    plan = models.CharField(
        'Plano',
        max_length=10,
        choices=Plan.choices,
        default=Plan.FREE,
    )
    plan_expires_at = models.DateField(
        'Vencimento do plano',
        null=True,
        blank=True,
        help_text='Quando preenchido, o acesso é bloqueado após esta data. Deixe em branco para plano sem vencimento (manual). Na renovação da assinatura, esta data será atualizada.',
    )
    last_session_key = models.CharField(
        'Ultima sessao ativa',
        max_length=40,
        blank=True,
    )

    def __str__(self) -> str:
        return str(self.user)


class Job(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Aberta'
        SEARCH_DONE = 'SEARCH_DONE', 'Busca feita'
        CANDIDATES_SENT = 'CANDIDATES_SENT', 'Candidatos enviados'
        CLOSED = 'CLOSED', 'Vaga finalizada'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='jobs',
    )
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    department = models.CharField(max_length=120, blank=True)
    seniority = models.CharField(max_length=80, blank=True)
    location = models.CharField(max_length=120, blank=True)
    stack = models.CharField(max_length=120, blank=True)
    contract_type = models.CharField(max_length=80, blank=True)
    salary_min = models.IntegerField(null=True, blank=True)
    salary_max = models.IntegerField(null=True, blank=True)
    language = models.CharField(max_length=120, blank=True)
    priority = models.CharField(max_length=40, blank=True)
    deadline = models.DateField(null=True, blank=True)
    must_have = models.TextField(blank=True)
    nice_to_have = models.TextField(blank=True)
    undesirable = models.TextField(blank=True)
    boolean_search = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return self.title


class Candidate(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='candidates',
    )
    name = models.CharField(max_length=160)
    current_title = models.CharField(max_length=160, blank=True)
    current_company = models.CharField(max_length=160, blank=True)
    location = models.CharField(max_length=160, blank=True)
    linkedin_url = models.URLField(max_length=300)
    summary = models.TextField(blank=True)
    skills = models.TextField(blank=True)
    technologies = models.TextField(blank=True)
    languages = models.TextField(blank=True)
    certifications = models.TextField(blank=True)
    seniority = models.CharField(max_length=80, blank=True)
    experience_time = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    average_tenure = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    ready_at = models.DateField(null=True, blank=True)
    resume_pdf = models.FileField(
        "Currículo PDF",
        upload_to=resume_upload_to,
        blank=True,
        null=True,
        help_text="PDF do currículo do candidato. Usado para avaliação mais precisa quando vinculado a uma vaga.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'linkedin_url'),
                name='core_candidate_user_linkedin_unique',
            ),
        ]

    def __str__(self) -> str:
        return self.name


class CandidateJob(models.Model):
    class PipelineStatus(models.TextChoices):
        FIRST_CONTACT = 'PRIMEIRO_CONTATO', 'Primeiro contato'
        RESPONDED = 'RESPONDEU', 'Respondeu'
        INTERVIEW = 'ENTREVISTA', 'Entrevista'
        TECH_INTERVIEW = 'ENTREVISTA_TECNICA', 'Entrevista tecnica'
        SENT_MANAGER = 'ENVIADO_GESTOR', 'Enviado para gestor'
        CANDIDATE_READY = 'CANDIDATO_PRONTO', 'Candidato pronto'
        SENT_CLIENT = 'ENVIADO_CLIENTE', 'Enviado para cliente'
        HIRED = 'CONTRATADO', 'Contratado'

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='candidate_links')
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='job_links')
    pipeline_status = models.CharField(max_length=32, choices=PipelineStatus.choices, blank=True)
    ready_at = models.DateField(null=True, blank=True)
    adherence_score = models.IntegerField(null=True, blank=True)
    technical_justification = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']
        unique_together = ('job', 'candidate')

    def save(self, *args, **kwargs):
        from django.utils import timezone

        previous_status = None
        if self.pk:
            previous_status = (
                CandidateJob.objects.filter(pk=self.pk)
                .values_list('pipeline_status', flat=True)
                .first()
            )
        if self.pipeline_status == self.PipelineStatus.CANDIDATE_READY:
            if not self.ready_at or previous_status != self.PipelineStatus.CANDIDATE_READY:
                now_date = timezone.now().date()
                self.ready_at = now_date
                if self.candidate_id:
                    Candidate.objects.filter(id=self.candidate_id).update(ready_at=now_date)
        super().save(*args, **kwargs)

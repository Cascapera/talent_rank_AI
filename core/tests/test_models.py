"""Testes dos modelos."""

import pytest
from django.contrib.auth import get_user_model

from core.models import Candidate, CandidateJob, Job, Profile, resume_upload_to

pytestmark = pytest.mark.django_db
User = get_user_model()


class TestResumeUploadTo:
    def test_returns_path_with_user_id_and_uuid(self):
        """Gera caminho resumes/{user_id}/{uuid}.pdf."""
        from unittest.mock import MagicMock

        instance = MagicMock()
        instance.user_id = 42
        path = resume_upload_to(instance, "curriculo.pdf")
        assert path.startswith("resumes/42/")
        assert path.endswith(".pdf")
        assert len(path.split("/")[-1]) == 32 + 4  # uuid.hex + .pdf

    def test_uses_shared_when_no_user_id(self):
        """Usa 'shared' quando user_id é None."""
        from unittest.mock import MagicMock

        instance = MagicMock()
        instance.user_id = None
        path = resume_upload_to(instance, "doc.pdf")
        assert path.startswith("resumes/shared/")


class TestProfile:
    def test_str_returns_user_str(self, user):
        profile, _ = Profile.objects.get_or_create(user=user)
        assert str(profile) == str(user)

    def test_default_plan_is_free(self, db):
        """Novo usuário sem Profile tem plano FREE por padrão."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        new_user = User.objects.create_user(
            username="newuser_plan",
            email="newplan@test.com",
            password="x",
        )
        profile, _ = Profile.objects.get_or_create(user=new_user)
        assert profile.plan == Profile.Plan.FREE


class TestJob:
    def test_str_returns_title(self, user):
        job = Job.objects.create(user=user, title="Dev Python")
        assert str(job) == "Dev Python"

    def test_default_status_is_open(self, user):
        job = Job.objects.create(user=user, title="Vaga")
        assert job.status == Job.Status.OPEN


class TestCandidate:
    def test_str_returns_name(self, user):
        candidate = Candidate.objects.create(
            user=user,
            name="João Silva",
            linkedin_url="https://linkedin.com/in/joao",
        )
        assert str(candidate) == "João Silva"

    def test_unique_per_user_linkedin(self, user):
        """Não permite mesmo linkedin_url para mesmo user."""
        from django.db import IntegrityError

        Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        with pytest.raises(IntegrityError):
            Candidate.objects.create(
                user=user,
                name="João 2",
                linkedin_url="https://linkedin.com/in/joao",
            )


class TestCandidateJob:
    def test_str_representation(self, user):
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="Maria",
            linkedin_url="https://linkedin.com/in/maria",
        )
        cj = CandidateJob.objects.create(job=job, candidate=candidate)
        assert cj.job_id == job.id
        assert cj.candidate_id == candidate.id

    def test_save_sets_ready_at_when_candidate_ready(self, user):
        """Ao salvar com CANDIDATE_READY, ready_at é preenchido e Candidate.ready_at atualizado."""
        from django.utils import timezone

        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="Maria",
            linkedin_url="https://linkedin.com/in/maria",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.CANDIDATE_READY,
        )
        assert cj.ready_at == timezone.now().date()
        candidate.refresh_from_db()
        assert candidate.ready_at == timezone.now().date()

    def test_save_updates_ready_at_when_status_changes_to_candidate_ready(self, user):
        """Ao alterar status para CANDIDATE_READY, ready_at é atualizado."""
        from django.utils import timezone

        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="Pedro",
            linkedin_url="https://linkedin.com/in/pedro",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.FIRST_CONTACT,
        )
        assert cj.ready_at is None
        cj.pipeline_status = CandidateJob.PipelineStatus.CANDIDATE_READY
        cj.save()
        cj.refresh_from_db()
        assert cj.ready_at == timezone.now().date()

    def test_parecer_and_parecer_type_fields(self, user):
        """CandidateJob armazena parecer e parecer_type corretamente."""
        job = Job.objects.create(user=user, title="Vaga Dev")
        candidate = Candidate.objects.create(
            user=user,
            name="Ana",
            linkedin_url="https://linkedin.com/in/ana",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
            parecer="Parecer resumido do candidato.",
            parecer_type=CandidateJob.ParecerType.RESUMIDO,
        )
        cj.refresh_from_db()
        assert cj.parecer == "Parecer resumido do candidato."
        assert cj.parecer_type == CandidateJob.ParecerType.RESUMIDO

    def test_parecer_type_choices(self):
        """ParecerType possui as opções esperadas."""
        assert CandidateJob.ParecerType.NONE == "NONE"
        assert CandidateJob.ParecerType.RESUMIDO == "RESUMIDO"
        assert CandidateJob.ParecerType.COMPLETO == "COMPLETO"
        assert CandidateJob.ParecerType.ROBUSTO == "ROBUSTO"

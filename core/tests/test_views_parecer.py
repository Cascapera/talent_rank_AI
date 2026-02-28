"""Testes das views de parecer."""

from unittest.mock import patch

import pytest
from django.urls import reverse

from core.models import Candidate, CandidateJob, Job

pytestmark = pytest.mark.django_db


class TestGenerateParecerView:
    def test_post_requires_login(self, client, user):
        """Endpoint exige autenticação."""
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
        )
        url = reverse("generate_parecer", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client.post(url, {"parecer_type": "RESUMIDO"})
        assert resp.status_code == 302  # redirect to login

    def test_post_method_only(self, client_logged, user):
        """GET não permitido."""
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
        )
        url = reverse("generate_parecer", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client_logged.get(url)
        assert resp.status_code == 405

    def test_rejects_invalid_status(self, client_logged, user):
        """Parecer só pode ser gerado para ENVIADO_GESTOR ou ENVIADO_CLIENTE."""
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.FIRST_CONTACT,
        )
        url = reverse("generate_parecer", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client_logged.post(url, {"parecer_type": "RESUMIDO"})
        assert resp.status_code == 400
        data = resp.json()
        assert "gestor" in data["error"].lower() or "cliente" in data["error"].lower()

    def test_rejects_invalid_parecer_type(self, client_logged, user):
        """Tipo de parecer inválido retorna 400."""
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
        )
        url = reverse("generate_parecer", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client_logged.post(url, {"parecer_type": "INVALIDO"})
        assert resp.status_code == 400
        assert "inválido" in resp.json()["error"].lower()

    def test_returns_existing_parecer_when_same_type(self, client_logged, user):
        """Se já existe parecer do mesmo tipo, retorna imediatamente sem chamar LLM."""
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
            parecer="Parecer já gerado.",
            parecer_type=CandidateJob.ParecerType.RESUMIDO,
        )
        url = reverse("generate_parecer", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        with patch("core.views._run_parecer_generation") as mock_run:
            resp = client_logged.post(url, {"parecer_type": "RESUMIDO"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["parecer"] == "Parecer já gerado."
        assert data["parecer_type"] == "RESUMIDO"
        mock_run.assert_not_called()

    def test_starts_generation_when_new_type(self, client_logged, user):
        """Tipo diferente inicia geração em background."""
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
            parecer="Parecer resumido.",
            parecer_type=CandidateJob.ParecerType.RESUMIDO,
        )
        url = reverse("generate_parecer", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        with patch("core.views._run_parecer_generation"):
            resp = client_logged.post(url, {"parecer_type": "COMPLETO"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"

    def test_404_for_other_user_job(self, client_logged, user):
        """Não permite acessar job de outro usuário."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        other_user = User.objects.create_user(
            username="other",
            email="other@test.com",
            password="x",
        )
        job = Job.objects.create(user=other_user, title="Vaga Outro")
        candidate = Candidate.objects.create(
            user=other_user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
        )
        url = reverse("generate_parecer", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client_logged.post(url, {"parecer_type": "RESUMIDO"})
        assert resp.status_code == 404


class TestParecerStatusView:
    def test_get_requires_login(self, client, user):
        """Endpoint exige autenticação."""
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
        )
        url = reverse("parecer_status", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client.get(url)
        assert resp.status_code == 302

    def test_returns_idle_when_no_cache_and_no_parecer(self, client_logged, user):
        """Retorna status idle quando não há cache nem parecer no banco."""
        from django.core.cache import cache

        cache.clear()
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
        )
        url = reverse("parecer_status", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client_logged.get(url)
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"

    def test_returns_completed_from_db_when_parecer_exists(self, client_logged, user):
        """Retorna status completed com parecer do banco quando não há cache."""
        from django.core.cache import cache

        cache.clear()
        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
            parecer="Parecer completo.",
            parecer_type=CandidateJob.ParecerType.COMPLETO,
        )
        url = reverse("parecer_status", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client_logged.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["parecer"] == "Parecer completo."
        assert data["parecer_type"] == "COMPLETO"

    def test_returns_from_cache_when_available(self, client_logged, user):
        """Retorna payload do cache quando disponível."""
        from django.core.cache import cache

        job = Job.objects.create(user=user, title="Vaga")
        candidate = Candidate.objects.create(
            user=user,
            name="João",
            linkedin_url="https://linkedin.com/in/joao",
        )
        cj = CandidateJob.objects.create(
            job=job,
            candidate=candidate,
            pipeline_status=CandidateJob.PipelineStatus.SENT_MANAGER,
        )
        cache.set(
            f"parecer_status_{cj.id}",
            {"status": "running"},
            timeout=60,
        )
        url = reverse("parecer_status", kwargs={"job_id": job.id, "candidate_job_id": cj.id})
        resp = client_logged.get(url)
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        cache.delete(f"parecer_status_{cj.id}")  # cleanup

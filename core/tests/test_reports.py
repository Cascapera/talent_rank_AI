"""Testes da tela de relatórios (R-24).

D-9 do diagnóstico: o funil era montado com um laço aninhado — para cada vaga, um
`links.count()`, oito `links.filter(...).count()` do funil e mais um `.count()` de
contratados. **10 queries por vaga, sobre até 50 vagas.**

Estes testes foram escritos **antes** da otimização e fixam o contexto que a tela
recebe. O `assertNumQueries` prova a redução sem depender de eu confiar na minha
própria contagem.
"""

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from core.models import Candidate, CandidateJob, Job

pytestmark = pytest.mark.django_db


ORDEM_FUNIL = [
    CandidateJob.PipelineStatus.FIRST_CONTACT,
    CandidateJob.PipelineStatus.RESPONDED,
    CandidateJob.PipelineStatus.INTERVIEW,
    CandidateJob.PipelineStatus.TECH_INTERVIEW,
    CandidateJob.PipelineStatus.SENT_MANAGER,
    CandidateJob.PipelineStatus.CANDIDATE_READY,
    CandidateJob.PipelineStatus.SENT_CLIENT,
    CandidateJob.PipelineStatus.HIRED,
]


@pytest.fixture
def premium(user):
    """A tela exige plano PREMIUM."""
    user.profile.plan = user.profile.Plan.PREMIUM
    user.profile.save()
    return user


@pytest.fixture
def cliente(premium):
    c = Client()
    c.force_login(premium)
    return c


def liga(job, user, nome, status=""):
    candidate = Candidate.objects.create(
        user=user,
        name=nome,
        linkedin_url=f"https://linkedin.com/in/{nome.lower().replace(' ', '-')}",
    )
    return CandidateJob.objects.create(job=job, candidate=candidate, pipeline_status=status)


class TestFunnelNumbers:
    """O que a tela mostra não pode mudar com a otimização."""

    def test_funnel_counts_each_stage(self, cliente, premium):
        vaga = Job.objects.create(user=premium, title="Dev Python")
        liga(vaga, premium, "Ana", CandidateJob.PipelineStatus.INTERVIEW)
        liga(vaga, premium, "Bia", CandidateJob.PipelineStatus.INTERVIEW)
        liga(vaga, premium, "Cleo", CandidateJob.PipelineStatus.HIRED)

        contexto = cliente.get("/relatorios/").context

        linha = contexto["jobs_with_funnel"][0]
        por_rotulo = {etapa["label"]: etapa["count"] for etapa in linha["funnel"]}
        assert por_rotulo["Entrevista"] == 2
        assert por_rotulo["Contratado"] == 1
        assert por_rotulo["Respondeu"] == 0

    def test_total_counts_links_without_a_stage(self, cliente, premium):
        """QUIRK que importa preservar: `total_candidates` da vaga conta **todos** os
        vínculos, inclusive os que ainda não têm etapa de funil. A soma do funil pode ser
        menor que o total — e isso é correto, não um bug de contagem."""
        vaga = Job.objects.create(user=premium, title="Dev Python")
        liga(vaga, premium, "Ana", CandidateJob.PipelineStatus.INTERVIEW)
        liga(vaga, premium, "Bia", "")

        linha = cliente.get("/relatorios/").context["jobs_with_funnel"][0]

        assert linha["total_candidates"] == 2
        assert sum(etapa["count"] for etapa in linha["funnel"]) == 1

    def test_hired_matches_the_funnel_entry(self, cliente, premium):
        vaga = Job.objects.create(user=premium, title="Dev Python")
        liga(vaga, premium, "Ana", CandidateJob.PipelineStatus.HIRED)

        linha = cliente.get("/relatorios/").context["jobs_with_funnel"][0]

        assert linha["hired"] == 1

    def test_funnel_keeps_the_column_order(self, cliente, premium):
        Job.objects.create(user=premium, title="Dev Python")

        contexto = cliente.get("/relatorios/").context

        esperado = [
            "Primeiro contato",
            "Respondeu",
            "Entrevista",
            "Entrevista tecnica",
            "Enviado para gestor",
            "Candidato pronto",
            "Enviado para cliente",
            "Contratado",
        ]
        assert contexto["funnel_headers"] == esperado
        assert [e["label"] for e in contexto["jobs_with_funnel"][0]["funnel"]] == esperado

    def test_job_without_candidates_shows_zeroes(self, cliente, premium):
        Job.objects.create(user=premium, title="Vaga vazia")

        linha = cliente.get("/relatorios/").context["jobs_with_funnel"][0]

        assert linha["total_candidates"] == 0
        assert all(etapa["count"] == 0 for etapa in linha["funnel"])
        assert linha["hired"] == 0

    def test_only_the_users_own_jobs(self, cliente, premium, django_user_model):
        outro = django_user_model.objects.create_user(username="outro", password="x")
        Job.objects.create(user=premium, title="Minha vaga")
        Job.objects.create(user=outro, title="Vaga alheia")

        contexto = cliente.get("/relatorios/").context

        assert [linha["job"].title for linha in contexto["jobs_with_funnel"]] == ["Minha vaga"]

    def test_at_most_fifty_jobs(self, cliente, premium):
        for i in range(55):
            Job.objects.create(user=premium, title=f"Vaga {i:02d}")

        contexto = cliente.get("/relatorios/").context

        assert len(contexto["jobs_with_funnel"]) == 50
        assert contexto["total_jobs"] == 55, "o total geral conta todas, não só as 50"


class TestSummaryNumbers:
    def test_general_summary(self, cliente, premium):
        vaga = Job.objects.create(user=premium, title="Dev Python")
        liga(vaga, premium, "Ana", CandidateJob.PipelineStatus.HIRED)
        liga(vaga, premium, "Bia", CandidateJob.PipelineStatus.INTERVIEW)

        contexto = cliente.get("/relatorios/").context

        assert contexto["total_jobs"] == 1
        assert contexto["total_candidates"] == 2
        assert contexto["total_links"] == 2
        assert contexto["candidates_hired"] == 1


class TestQueryCount:
    """A razão de existir do R-24."""

    def _queries_da_tela(self, cliente) -> int:
        with CaptureQueriesContext(connection) as captura:
            cliente.get("/relatorios/")
        return len(captura.captured_queries)

    def test_the_funnel_does_not_scale_with_the_number_of_jobs(self, cliente, premium):
        """O teste que prova a correção: **o número de queries não pode crescer com o
        número de vagas.**

        Antes do R-24 eram 10 queries por vaga. É uma afirmação melhor que um número
        fixo: não quebra quando alguém adicionar uma query legítima à tela, mas quebra
        na hora se o laço aninhado voltar.
        """
        for i in range(12):
            vaga = Job.objects.create(user=premium, title=f"Vaga {i:02d}")
            liga(vaga, premium, f"Candidato {i:02d}", CandidateJob.PipelineStatus.INTERVIEW)

        com_doze = self._queries_da_tela(cliente)

        Job.objects.all().delete()
        vaga = Job.objects.create(user=premium, title="Unica")
        liga(vaga, premium, "Ana", CandidateJob.PipelineStatus.INTERVIEW)

        com_uma = self._queries_da_tela(cliente)

        assert com_doze == com_uma, (
            f"o funil ainda faz query por vaga: {com_doze} queries com 12 vagas "
            f"contra {com_uma} com 1"
        )

        # Limite absoluto com folga, só para registrar a ordem de grandeza. A afirmação
        # que importa é a de cima; esta existe para o número não subir despercebido.
        assert com_doze <= 25, f"a tela passou a fazer {com_doze} queries"

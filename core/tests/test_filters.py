"""Characterization tests dos filtros e da paginação (T-6 da seção 6 / R-38).

Rede de segurança para o R-15, que vai extrair o helper de filtros + querystring das
duas views. O item declarava pré-requisito "R-19 (testes de filtro)", mas o R-19 é outra
coisa (chave de cache por usuário) — a referência estava quebrada e **não existia teste
nenhum tocando em filtro ou querystring**.

Como em R-05, R-06, R-07 e R-33: registram o que o sistema faz HOJE. O que estiver
marcado como QUIRK está fixado de propósito.

Cobrem os dois blocos que o R-15 vai unificar:
  - `talent_pool`  — 9 filtros `icontains`, paginação de 10, querystring com `&` na frente
  - `job_detail`   — 8 filtros + o comportamento de filtro salvo em sessão

⚠️ Rodam em SQLite, então `_apply_unaccent_filter` cai no ramo `icontains` (o ramo
`unaccent` só existe em PostgreSQL). É o mesmo que o CI sempre exercitou.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Candidate, CandidateJob, Job

pytestmark = pytest.mark.django_db


def make_candidate(user, nome, **extra):
    return Candidate.objects.create(
        user=user,
        name=nome,
        linkedin_url=f"https://linkedin.com/in/{nome.lower().replace(' ', '-')}",
        **extra,
    )


@pytest.fixture
def job(user):
    return Job.objects.create(user=user, title="Dev Python")


class TestTalentPoolFilters:
    """Os 9 filtros do banco de talentos, todos `icontains`."""

    @pytest.mark.parametrize(
        "param,campo,valor,outro",
        [
            ("name", "name", "Ana Souza", "Bia Lima"),
            ("location", "location", "São Paulo", "Recife"),
            ("seniority", "seniority", "Senior", "Junior"),
            ("company", "current_company", "ACME", "Globex"),
            ("technologies", "technologies", "Django", "Rails"),
            ("current_title", "current_title", "Engenheira", "Designer"),
            ("skills", "skills", "Python", "Ruby"),
            ("certifications", "certifications", "AWS SAA", "CKA"),
            ("languages", "languages", "Inglês", "Espanhol"),
        ],
    )
    def test_each_filter_narrows_the_list(self, client_logged, user, param, campo, valor, outro):
        if campo == "name":
            make_candidate(user, valor)
            make_candidate(user, outro)
        else:
            make_candidate(user, "Ana Souza", **{campo: valor})
            make_candidate(user, "Bia Lima", **{campo: outro})

        resposta = client_logged.get("/talentos/", {param: valor})

        nomes = [c.name for c in resposta.context["candidates"]]
        assert len(nomes) == 1, f"{param} nao filtrou: {nomes}"

    def test_filter_is_case_insensitive_and_partial(self, client_logged, user):
        make_candidate(user, "Ana Souza", skills="Python, Django")

        resposta = client_logged.get("/talentos/", {"skills": "pyth"})

        assert len(resposta.context["candidates"]) == 1

    def test_filters_combine_with_and(self, client_logged, user):
        make_candidate(user, "Ana Souza", seniority="Senior", location="São Paulo")
        make_candidate(user, "Bia Lima", seniority="Senior", location="Recife")

        resposta = client_logged.get("/talentos/", {"seniority": "Senior", "location": "Recife"})

        nomes = [c.name for c in resposta.context["candidates"]]
        assert nomes == ["Bia Lima"]

    def test_blank_filter_is_ignored(self, client_logged, user):
        make_candidate(user, "Ana Souza")
        make_candidate(user, "Bia Lima")

        resposta = client_logged.get("/talentos/", {"name": "   "})

        assert len(resposta.context["candidates"]) == 2

    def test_filters_dict_goes_to_the_template(self, client_logged, user):
        make_candidate(user, "Ana Souza")

        resposta = client_logged.get("/talentos/", {"name": "  Ana  ", "skills": "Python"})

        filtros = resposta.context["filters"]
        assert filtros["name"] == "Ana", "o valor vai aparado para o template"
        assert filtros["skills"] == "Python"
        assert filtros["location"] == ""


class TestTalentPoolPagination:
    def test_ten_per_page(self, client_logged, user):
        for i in range(12):
            make_candidate(user, f"Candidato {i:02d}")

        resposta = client_logged.get("/talentos/")

        assert len(resposta.context["candidates"]) == 10
        assert resposta.context["page_obj"].paginator.num_pages == 2

    def test_second_page_has_the_rest(self, client_logged, user):
        for i in range(12):
            make_candidate(user, f"Candidato {i:02d}")

        resposta = client_logged.get("/talentos/", {"page": 2})

        assert len(resposta.context["candidates"]) == 2

    def test_querystring_keeps_the_filters_and_starts_with_an_ampersand(self, client_logged, user):
        """QUIRK: a querystring já vem com `&` na frente, para ser colada depois de
        `?page=N` no template. Quem extrair o helper precisa manter isso, ou os links
        de paginação viram `?page=2name=Ana`."""
        make_candidate(user, "Ana Souza", skills="Python")

        resposta = client_logged.get("/talentos/", {"name": "Ana", "skills": "Python"})

        qs = resposta.context["query_string"]
        assert qs.startswith("&")
        assert "name=Ana" in qs
        assert "skills=Python" in qs

    def test_querystring_is_empty_without_filters(self, client_logged, user):
        make_candidate(user, "Ana Souza")

        resposta = client_logged.get("/talentos/")

        assert resposta.context["query_string"] == ""

    def test_querystring_omits_blank_filters(self, client_logged, user):
        make_candidate(user, "Ana Souza")

        resposta = client_logged.get("/talentos/", {"name": "Ana", "location": ""})

        assert "location" not in resposta.context["query_string"]


class TestTalentPoolOrdering:
    def test_most_recently_updated_first(self, client_logged, user):
        """Ordem é `-updated_at, -created_at`.

        Os timestamps são gravados com `.update()` de propósito: `auto_now` empata na
        resolução do SQLite quando as escritas caem no mesmo instante, e aí o desempate
        vira o `-created_at` — o teste passava sozinho e falhava na suíte cheia.
        """
        ana = make_candidate(user, "Ana Souza")
        bia = make_candidate(user, "Bia Lima")

        agora = timezone.now()
        Candidate.objects.filter(pk=bia.pk).update(updated_at=agora - timedelta(hours=2))
        Candidate.objects.filter(pk=ana.pk).update(updated_at=agora)

        resposta = client_logged.get("/talentos/")

        nomes = [c.name for c in resposta.context["candidates"]]
        assert nomes == ["Ana Souza", "Bia Lima"]


class TestJobDetailFilters:
    """Os filtros da tela da vaga, que além de filtrar são salvos em sessão."""

    def _link(self, job, candidate, **extra):
        return CandidateJob.objects.create(job=job, candidate=candidate, **extra)

    def test_pipeline_status_filter(self, client_logged, user, job):
        self._link(job, make_candidate(user, "Ana Souza"), pipeline_status="SENT")
        self._link(job, make_candidate(user, "Bia Lima"), pipeline_status="HIRED")

        resposta = client_logged.get(f"/vagas/{job.id}/", {"pipeline_status": "HIRED"})

        nomes = [link.candidate.name for link in resposta.context["candidate_links"]]
        assert nomes == ["Bia Lima"]

    def test_candidate_name_filter(self, client_logged, user, job):
        self._link(job, make_candidate(user, "Ana Souza"))
        self._link(job, make_candidate(user, "Bia Lima"))

        resposta = client_logged.get(f"/vagas/{job.id}/", {"candidate_name": "Bia"})

        nomes = [link.candidate.name for link in resposta.context["candidate_links"]]
        assert nomes == ["Bia Lima"]

    def test_filters_are_saved_in_the_session(self, client_logged, user, job):
        self._link(job, make_candidate(user, "Ana Souza"))

        client_logged.get(f"/vagas/{job.id}/", {"candidate_name": "Ana"})

        salvos = client_logged.session[f"job_filters_{job.id}"]
        assert salvos["candidate_name"] == "Ana"

    def test_a_bare_visit_redirects_to_the_saved_filters(self, client_logged, user, job):
        """QUIRK com consequência: entrar na vaga sem parâmetro nenhum **redireciona**
        para a última busca salva. A recrutadora volta à tela e reencontra o filtro de
        antes — mas quem espera um GET simples leva um 302."""
        self._link(job, make_candidate(user, "Ana Souza"))
        client_logged.get(f"/vagas/{job.id}/", {"candidate_name": "Ana"})

        resposta = client_logged.get(f"/vagas/{job.id}/")

        assert resposta.status_code == 302
        assert "candidate_name=Ana" in resposta.url

    def test_clear_filters_wipes_the_session_and_does_not_redirect(self, client_logged, user, job):
        self._link(job, make_candidate(user, "Ana Souza"))
        client_logged.get(f"/vagas/{job.id}/", {"candidate_name": "Ana"})

        resposta = client_logged.get(f"/vagas/{job.id}/", {"clear_filters": "1"})

        assert resposta.status_code == 200
        assert f"job_filters_{job.id}" not in client_logged.session

    def test_saved_filters_are_per_job(self, client_logged, user, job):
        outra = Job.objects.create(user=user, title="Dev Go")
        self._link(job, make_candidate(user, "Ana Souza"))
        client_logged.get(f"/vagas/{job.id}/", {"candidate_name": "Ana"})

        resposta = client_logged.get(f"/vagas/{outra.id}/")

        assert resposta.status_code == 200, "vaga sem filtro salvo nao redireciona"

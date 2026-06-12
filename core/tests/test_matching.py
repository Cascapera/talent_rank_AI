"""Testes do pré-match vaga x candidato (core/matching.py)."""

from core.matching import (
    compute_match,
    job_has_match_criteria,
    match_candidates_for_job,
)
from core.models import Candidate, Job


def make_job(**kwargs):
    defaults = {
        "title": "Desenvolvedor Backend",
        "must_have": "",
        "stack": "",
        "nice_to_have": "",
        "seniority": "",
        "language": "",
    }
    defaults.update(kwargs)
    return Job(**defaults)


def make_candidate(**kwargs):
    defaults = {
        "name": "Candidato Teste",
        "skills": "",
        "technologies": "",
        "languages": "",
        "certifications": "",
        "summary": "",
        "seniority": "",
        "current_title": "",
    }
    defaults.update(kwargs)
    return Candidate(**defaults)


class TestJobHasMatchCriteria:
    def test_vaga_sem_requisitos(self):
        assert job_has_match_criteria(make_job()) is False

    def test_vaga_com_must_have(self):
        assert job_has_match_criteria(make_job(must_have="Python")) is True

    def test_vaga_so_com_senioridade(self):
        assert job_has_match_criteria(make_job(seniority="Senior")) is True


class TestComputeMatch:
    def test_match_total_must_have(self):
        job = make_job(must_have="Python, Django")
        candidate = make_candidate(skills="Python, Django, REST")
        assert compute_match(job, candidate)["score"] == 100

    def test_match_parcial_must_have(self):
        job = make_job(must_have="Python, Django, Kafka, AWS")
        candidate = make_candidate(skills="Python, Django")
        assert compute_match(job, candidate)["score"] == 50

    def test_sem_match(self):
        job = make_job(must_have="Java, Spring")
        candidate = make_candidate(skills="Python, Django")
        assert compute_match(job, candidate)["score"] == 0

    def test_match_ignora_acentos_e_caixa(self):
        job = make_job(must_have="gestão de projetos")
        candidate = make_candidate(skills="GESTAO DE PROJETOS")
        assert compute_match(job, candidate)["score"] == 100

    def test_match_por_sinonimo(self):
        job = make_job(must_have="k8s")
        candidate = make_candidate(technologies="Docker, Kubernetes")
        assert compute_match(job, candidate)["score"] == 100

    def test_senioridade_igual_ou_acima_atende(self):
        job = make_job(must_have="Python", seniority="Pleno")
        senior = make_candidate(skills="Python", seniority="Senior")
        junior = make_candidate(skills="Python", seniority="Junior")
        assert compute_match(job, senior)["score"] == 100
        assert compute_match(job, junior)["score"] < 100

    def test_idioma_considera_languages_do_candidato(self):
        job = make_job(must_have="Python", language="Inglês")
        candidate = make_candidate(skills="Python", languages="Português, Inglês")
        assert compute_match(job, candidate)["score"] == 100

    def test_pesos_normalizados_por_categorias_preenchidas(self):
        # Vaga só com must_have e stack: candidato com 100% must_have e 0% stack
        # deve ter score 50/(50+20) ~= 71
        job = make_job(must_have="Python", stack="Kafka")
        candidate = make_candidate(skills="Python")
        assert compute_match(job, candidate)["score"] == 71

    def test_matched_terms_sem_duplicados(self):
        job = make_job(must_have="Python", stack="Python")
        candidate = make_candidate(skills="Python")
        assert compute_match(job, candidate)["matched_terms"] == ["Python"]


class TestMatchCandidatesForJob:
    def test_filtra_pelo_minimo_e_ordena_por_score(self):
        job = make_job(must_have="Python, Django")
        forte = make_candidate(name="Forte", skills="Python, Django")
        medio = make_candidate(name="Medio", skills="Python")
        fraco = make_candidate(name="Fraco", skills="Java")

        results = match_candidates_for_job(job, [fraco, medio, forte], min_score=50)

        assert [r["candidate"].name for r in results] == ["Forte", "Medio"]
        assert results[0]["score"] == 100
        assert results[1]["score"] == 50

    def test_minimo_zero_inclui_todos(self):
        job = make_job(must_have="Python")
        fraco = make_candidate(name="Fraco", skills="Java")
        results = match_candidates_for_job(job, [fraco], min_score=0)
        assert len(results) == 1

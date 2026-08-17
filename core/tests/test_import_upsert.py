"""Characterization tests do upsert de candidato na importação (R-05).

Estes testes NÃO julgam se o comportamento é correto: eles fixam o que o sistema faz
hoje, para que R-08 (extrair `_upsert_candidate` e unificar as 4 cópias do bloco de
persistência) possa provar que nada mudou.

Se um destes testes falhar depois de uma refatoração, ou a refatoração alterou
comportamento — e aí não é refatoração —, ou o comportamento mudou de propósito e o
teste precisa ser reescrito de forma consciente, com o porquê registrado.

Os pontos marcados como QUIRK são comportamentos que provavelmente não são intencionais.
Estão fixados assim mesmo, de propósito: corrigir é decisão separada, em PR próprio.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from core.models import Candidate, CandidateJob, Job
from core.pdf_extractor import import_candidates_from_folder

pytestmark = pytest.mark.django_db

User = get_user_model()

WEIGHTS = {"skills": 40, "technologies": 35, "experience": 25}


def llm_row(**overrides) -> dict:
    """Uma linha de resultado do LLM, no formato que extract_candidates_batch_with_llm devolve."""
    row = {
        "name": "Ana Souza",
        "linkedin_url": "https://linkedin.com/in/ana-souza",
        "location": "São Paulo",
        "current_title": "Engenheira de Software",
        "current_company": "ACME",
        "skills": ["Python", "Django"],
        "technologies": ["PostgreSQL"],
        "languages": ["Português", "Inglês"],
        "certifications": ["AWS SAA"],
        "experience_time_years": 5.5,
        "average_tenure_years": 2.5,
        "seniority": "Senior",
        "adherence": 87,
        "technical_justification": "Boa aderência",
    }
    row.update(overrides)
    return row


@pytest.fixture
def pdf_dir(tmp_path, settings):
    """Pasta com PDFs falsos + MEDIA_ROOT isolado (o upsert salva o currículo em disco)."""
    settings.MEDIA_ROOT = tmp_path / "media"
    folder = tmp_path / "pdfs"
    folder.mkdir()
    return folder


def make_pdfs(folder, count=1):
    """Cria `count` PDFs falsos. O conteúdo não importa: o LLM está mockado."""
    paths = []
    for i in range(count):
        p = folder / f"{i:04d}.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        paths.append(p)
    return paths


def run_import(folder, results, **kwargs):
    """Roda a importação com o LLM mockado devolvendo `results`."""
    with patch(
        "core.pdf_extractor.extract_candidates_batch_with_llm", return_value=results
    ) as mock_llm:
        result = import_candidates_from_folder(
            str(folder),
            job_description="Vaga de teste",
            weights=WEIGHTS,
            **kwargs,
        )
    return result, mock_llm


class TestCreate:
    def test_creates_candidate_with_all_fields(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row()], user_id=user.id)

        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["total"] == 1

        c = Candidate.objects.get()
        assert c.name == "Ana Souza"
        assert c.current_title == "Engenheira de Software"
        assert c.current_company == "ACME"
        assert c.location == "São Paulo"
        assert c.linkedin_url == "https://linkedin.com/in/ana-souza"
        assert c.seniority == "Senior"
        assert c.experience_time == Decimal("5.5")
        assert c.average_tenure == Decimal("2.5")

    def test_lists_are_joined_with_comma_and_space(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row()], user_id=user.id)

        c = Candidate.objects.get()
        assert c.skills == "Python, Django"
        assert c.technologies == "PostgreSQL"
        assert c.languages == "Português, Inglês"
        assert c.certifications == "AWS SAA"

    def test_candidate_is_bound_to_user_id(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row()], user_id=user.id)

        assert Candidate.objects.get().user_id == user.id

    def test_none_text_fields_become_empty_string(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        row = llm_row(current_title=None, current_company=None, location=None, seniority=None)
        run_import(pdf_dir, [row], user_id=user.id)

        c = Candidate.objects.get()
        assert c.current_title == ""
        assert c.current_company == ""
        assert c.location == ""
        assert c.seniority == ""

    def test_numeric_fields_accept_none(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        row = llm_row(experience_time_years=None, average_tenure_years=None)
        result, _ = run_import(pdf_dir, [row], user_id=user.id)

        assert result["created"] == 1
        c = Candidate.objects.get()
        assert c.experience_time is None
        assert c.average_tenure is None

    def test_resume_pdf_is_saved_on_create(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row()], user_id=user.id)

        c = Candidate.objects.get()
        assert c.resume_pdf
        assert c.resume_pdf.name.startswith(f"resumes/{user.id}/")
        assert c.resume_pdf.name.endswith(".pdf")

    # transaction=True: o IntegrityError abaixo quebraria o bloco atomic que o
    # django_db normal abre em volta do teste, impedindo qualquer query seguinte.
    # Em produção o job roda em thread própria, com autocommit, e segue adiante.
    @pytest.mark.django_db(transaction=True)
    def test_without_user_id_the_import_fails_and_counts_as_error(self, pdf_dir):
        """QUIRK: Candidate.user é obrigatório. Sem user_id o create estoura IntegrityError,
        que é engolido pelo except e vira `errors`, sem propagar para quem chamou.
        Na prática a view sempre passa request.user.id, então este caminho não é
        alcançável hoje — mas o silêncio do except é real e fica registrado."""
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row()])

        assert result["created"] == 0
        assert result["errors"] == 1
        assert result["error_details"] and "Erro ao salvar" in result["error_details"][0]
        assert Candidate.objects.count() == 0


class TestUpdate:
    def test_updates_candidate_matched_by_linkedin_url(self, pdf_dir, user):
        Candidate.objects.create(
            user=user,
            name="Nome Antigo",
            linkedin_url="https://linkedin.com/in/ana-souza",
            seniority="Pleno",
        )
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row()], user_id=user.id)

        assert result["created"] == 0
        assert result["updated"] == 1
        assert Candidate.objects.count() == 1

        c = Candidate.objects.get()
        assert c.name == "Ana Souza"
        assert c.seniority == "Senior"

    def test_linkedin_url_match_is_case_insensitive(self, pdf_dir, user):
        Candidate.objects.create(
            user=user,
            name="Nome Antigo",
            linkedin_url="https://LinkedIn.com/in/ANA-SOUZA",
        )
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row()], user_id=user.id)

        assert result["created"] == 0
        assert result["updated"] == 1
        assert Candidate.objects.count() == 1

    def test_unchanged_candidate_is_counted_and_the_totals_add_up(self, pdf_dir, user):
        """R-32: candidato que já existia e no qual nada mudou entra em `unchanged`.

        Antes ele sumia da contabilidade: não era `created`, não era `updated`, não era
        `skipped` nem `errors`. A recrutadora reimportava 10 PDFs idênticos e lia
        "0 criados, 0 atualizados, 0 ignorados" — números que não fecham com o total.

        A asserção que importa é a última: a soma tem que bater com `total`.
        """
        Candidate.objects.create(
            user=user,
            name="Ana Souza",
            current_title="Engenheira de Software",
            current_company="ACME",
            location="São Paulo",
            linkedin_url="https://linkedin.com/in/ana-souza",
            summary="",
            skills="Python, Django",
            technologies="PostgreSQL",
            languages="Português, Inglês",
            certifications="AWS SAA",
            seniority="Senior",
            experience_time=Decimal("5.5"),
            average_tenure=Decimal("2.5"),
        )
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row()], user_id=user.id)

        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["unchanged"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["total"] == 1
        assert (
            result["created"]
            + result["updated"]
            + result["unchanged"]
            + result["skipped"]
            + result["errors"]
            == result["total"]
        )

    def test_resume_pdf_is_resaved_even_when_nothing_changed(self, pdf_dir, user):
        """QUIRK: o PDF é regravado em disco em toda importação, mesmo sem alteração
        de dado. Gera arquivo novo (nome com uuid) a cada rodada."""
        existing = Candidate.objects.create(
            user=user,
            name="Ana Souza",
            linkedin_url="https://linkedin.com/in/ana-souza",
        )
        assert not existing.resume_pdf

        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row()], user_id=user.id)

        existing.refresh_from_db()
        assert existing.resume_pdf

    def test_summary_is_always_wiped_on_update(self, pdf_dir, user):
        """QUIRK: o payload fixa summary="" independentemente do que veio do LLM.
        Um candidato que já tinha resumo perde o resumo ao ser reimportado."""
        Candidate.objects.create(
            user=user,
            name="Ana Souza",
            linkedin_url="https://linkedin.com/in/ana-souza",
            summary="Resumo escrito à mão pela recrutadora",
        )
        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row(summary="resumo vindo do LLM")], user_id=user.id)

        assert Candidate.objects.get().summary == ""


class TestSkip:
    def test_skips_row_without_name(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row(name="")], user_id=user.id)

        assert result["skipped"] == 1
        assert result["created"] == 0
        assert Candidate.objects.count() == 0

    def test_skips_row_without_linkedin_url(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row(linkedin_url="")], user_id=user.id)

        assert result["skipped"] == 1
        assert result["created"] == 0
        assert Candidate.objects.count() == 0

    def test_skipped_row_does_not_stop_the_others(self, pdf_dir, user):
        make_pdfs(pdf_dir, count=3)
        rows = [
            llm_row(name="", linkedin_url="https://linkedin.com/in/a"),
            llm_row(name="Bruno", linkedin_url="https://linkedin.com/in/b"),
            llm_row(name="Carla", linkedin_url="https://linkedin.com/in/c"),
        ]
        result, _ = run_import(pdf_dir, rows, user_id=user.id)

        assert result["skipped"] == 1
        assert result["created"] == 2
        assert result["total"] == 3
        assert Candidate.objects.count() == 2


class TestSharedPool:
    def test_shared_pool_updates_candidate_of_another_user(self, pdf_dir, user):
        outro = User.objects.create_user(username="outro", password="x")
        Candidate.objects.create(
            user=outro,
            name="Ana Souza",
            linkedin_url="https://linkedin.com/in/ana-souza",
        )
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row()], user_id=user.id, shared_pool=True)

        assert result["created"] == 0
        assert result["updated"] == 1
        assert Candidate.objects.count() == 1
        # O dono não muda: o update não reatribui o candidato ao importador.
        assert Candidate.objects.get().user_id == outro.id

    def test_without_shared_pool_candidate_of_another_user_is_not_matched(self, pdf_dir, user):
        outro = User.objects.create_user(username="outro", password="x")
        Candidate.objects.create(
            user=outro,
            name="Ana Souza",
            linkedin_url="https://linkedin.com/in/ana-souza",
        )
        make_pdfs(pdf_dir)
        result, _ = run_import(pdf_dir, [llm_row()], user_id=user.id, shared_pool=False)

        assert result["created"] == 1
        assert Candidate.objects.count() == 2
        assert Candidate.objects.filter(user=user).count() == 1


class TestCandidateJob:
    def test_creates_link_with_adherence_when_job_id_given(self, pdf_dir, user):
        job = Job.objects.create(user=user, title="Vaga Python")
        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row()], user_id=user.id, job_id=job.id)

        cj = CandidateJob.objects.get()
        assert cj.job_id == job.id
        assert cj.adherence_score == 87
        assert cj.technical_justification == "Boa aderência"

    def test_reimport_updates_the_link_instead_of_duplicating(self, pdf_dir, user):
        job = Job.objects.create(user=user, title="Vaga Python")
        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row()], user_id=user.id, job_id=job.id)
        run_import(
            pdf_dir,
            [llm_row(adherence=42, technical_justification="Reavaliado")],
            user_id=user.id,
            job_id=job.id,
        )

        assert CandidateJob.objects.count() == 1
        cj = CandidateJob.objects.get()
        assert cj.adherence_score == 42
        assert cj.technical_justification == "Reavaliado"

    def test_no_link_created_without_job_id(self, pdf_dir, user):
        make_pdfs(pdf_dir)
        run_import(pdf_dir, [llm_row()], user_id=user.id)

        assert CandidateJob.objects.count() == 0


class TestLlmContract:
    def test_llm_receives_the_pdf_batch_and_the_job_context(self, pdf_dir, user):
        paths = make_pdfs(pdf_dir, count=2)
        rows = [
            llm_row(name="Ana", linkedin_url="https://linkedin.com/in/a"),
            llm_row(name="Bruno", linkedin_url="https://linkedin.com/in/b"),
        ]
        _, mock_llm = run_import(pdf_dir, rows, user_id=user.id, role_title="Dev Python / Backend")

        assert mock_llm.call_count == 1
        args, kwargs = mock_llm.call_args
        assert args[0] == paths
        assert kwargs["job_description"] == "Vaga de teste"
        assert kwargs["weights"] == WEIGHTS
        # role_title é fatiado por "/" antes de chegar ao LLM
        assert kwargs["role_titles"] == ["Dev Python", "Backend"]

    def test_results_are_matched_to_pdfs_by_position(self, pdf_dir, user):
        make_pdfs(pdf_dir, count=2)
        rows = [
            llm_row(name="Ana", linkedin_url="https://linkedin.com/in/a"),
            llm_row(name="Bruno", linkedin_url="https://linkedin.com/in/b"),
        ]
        run_import(pdf_dir, rows, user_id=user.id)

        assert set(Candidate.objects.values_list("name", flat=True)) == {"Ana", "Bruno"}


class TestFolder:
    def test_raises_when_folder_does_not_exist(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_candidates_from_folder(
                str(tmp_path / "nao-existe"),
                job_description="x",
                weights=WEIGHTS,
            )

    def test_empty_folder_returns_zeroed_result_without_calling_llm(self, pdf_dir, user):
        result, mock_llm = run_import(pdf_dir, [], user_id=user.id)

        assert result == {
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
            "errors": 0,
            "total": 0,
            "error_details": [],
        }
        assert mock_llm.call_count == 0

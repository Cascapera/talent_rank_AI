"""Testes do `CandidateJob.save()` e da query extra que ele fazia (R-26).

D-10 do diagnóstico: o `save()` lia o `pipeline_status` anterior do banco em **todo**
save — inclusive nos que não têm nada a ver com o funil, como gravar um parecer ou uma
aderência. E a importação grava aderência para cada candidato de cada lote.

A leitura só importa num caso: o candidato já tem `ready_at` e o status novo é
"Candidato pronto" — aí precisamos saber se ele *acabou* de entrar nesse estado ou já
estava. Agora a consulta só acontece nesse caso.

Os 13 testes de `test_models.py` cobrem o comportamento; estes cobrem o **custo**.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import Candidate, CandidateJob, Job

pytestmark = pytest.mark.django_db


@pytest.fixture
def vinculo(user):
    job = Job.objects.create(user=user, title="Dev Python")
    candidate = Candidate.objects.create(
        user=user, name="Ana Souza", linkedin_url="https://linkedin.com/in/ana-souza"
    )
    return CandidateJob.objects.create(job=job, candidate=candidate)


def _queries(fn) -> int:
    with CaptureQueriesContext(connection) as captura:
        fn()
    return len(captura.captured_queries)


class TestTheExtraQueryIsGone:
    def test_saving_an_unrelated_field_does_not_read_the_previous_status(self, vinculo):
        """O caso comum, e o que a importação faz a cada candidato de cada lote."""
        vinculo.adherence_score = 80

        assert _queries(vinculo.save) == 1, "só o UPDATE, sem a leitura extra"

    def test_saving_a_parecer_does_not_read_the_previous_status(self, vinculo):
        vinculo.parecer = "Candidato aderente."

        assert _queries(vinculo.save) == 1

    def test_moving_to_an_intermediate_stage_does_not_read_either(self, vinculo):
        vinculo.pipeline_status = CandidateJob.PipelineStatus.INTERVIEW

        assert _queries(vinculo.save) == 1


class TestTheQueryStillHappensWhenItMatters:
    def test_already_ready_with_a_date_needs_the_previous_status(self, vinculo):
        """Aqui a consulta se paga: com `ready_at` já preenchido, é ela que diz se o
        candidato *acabou* de entrar em "pronto" ou já estava."""
        vinculo.pipeline_status = CandidateJob.PipelineStatus.CANDIDATE_READY
        vinculo.save()
        vinculo.refresh_from_db()

        assert vinculo.ready_at is not None
        assert _queries(vinculo.save) > 1


class TestBehaviourIsUnchanged:
    """O R-26 é otimização: o que o `save()` decide não pode mudar."""

    def test_entering_ready_sets_the_date_on_both_records(self, vinculo):
        vinculo.pipeline_status = CandidateJob.PipelineStatus.CANDIDATE_READY
        vinculo.save()

        vinculo.refresh_from_db()
        vinculo.candidate.refresh_from_db()
        hoje = timezone.now().date()
        assert vinculo.ready_at == hoje
        assert vinculo.candidate.ready_at == hoje

    def test_staying_ready_keeps_the_original_date(self, vinculo):
        vinculo.pipeline_status = CandidateJob.PipelineStatus.CANDIDATE_READY
        vinculo.save()
        CandidateJob.objects.filter(pk=vinculo.pk).update(ready_at="2020-01-01")
        vinculo.refresh_from_db()

        vinculo.save()

        vinculo.refresh_from_db()
        assert str(vinculo.ready_at) == "2020-01-01", (
            "quem ja estava pronto nao pode ter a data reescrita a cada save"
        )

    def test_returning_to_ready_after_leaving_sets_a_new_date(self, vinculo):
        vinculo.pipeline_status = CandidateJob.PipelineStatus.CANDIDATE_READY
        vinculo.save()
        CandidateJob.objects.filter(pk=vinculo.pk).update(ready_at="2020-01-01")

        vinculo.refresh_from_db()
        vinculo.pipeline_status = CandidateJob.PipelineStatus.INTERVIEW
        vinculo.save()
        vinculo.pipeline_status = CandidateJob.PipelineStatus.CANDIDATE_READY
        vinculo.save()

        vinculo.refresh_from_db()
        assert vinculo.ready_at == timezone.now().date()

    def test_other_stages_never_touch_the_date(self, vinculo):
        vinculo.pipeline_status = CandidateJob.PipelineStatus.HIRED
        vinculo.save()

        vinculo.refresh_from_db()
        assert vinculo.ready_at is None

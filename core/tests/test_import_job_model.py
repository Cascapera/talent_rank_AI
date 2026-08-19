"""Testes do estado dos jobs de background no banco (R-20a, atualizados no R-20b).

O R-20a criou a tabela e escrevia nela **e** no cache; o **R-20b** removeu o cache e
moveu a leitura para cá. As asserções que falavam de cache foram reescritas contra o
`payload` da linha — que é o mesmo dicionário, no mesmo formato, em outro lugar.

O que estes testes protegem, em ordem de importância:

1. **O rastreamento não pode derrubar o job.** Se o banco recusar a escrita da linha, a
   importação tem que seguir. É a razão de os três helpers engolirem exceção.
2. A linha é criada, atualizada e fechada nos três fluxos.
3. O `payload` carrega o que a tela mostra — progresso ao vivo e resumo final.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache

from core.models import ImportJob, Job
from core.services import import_service
from core.services.import_service import (
    _finish_import_job,
    _run_talent_pool_import,
    _track_progress,
    start_import_job,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def cache_limpo():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def pasta(tmp_path):
    p = tmp_path / "pdfs"
    p.mkdir()
    return p


def _roda_talent_pool(pasta, user, resultado=None, erro=None, import_job_id=None):
    alvo = {"return_value": resultado or {"created": 0, "updated": 0, "total": 0}}
    if erro is not None:
        alvo = {"side_effect": erro}
    if import_job_id is None:
        import_job_id = start_import_job(user_id=user.id, kind=ImportJob.Kind.TALENT_POOL_IMPORT)
    with patch.object(import_service, "import_candidates_from_folder_no_ranking", **alvo):
        _run_talent_pool_import(pasta, False, user.id, False, import_job_id)


class TestTrackingNeverBreaksTheJob:
    """A garantia mais importante do item: rastreamento é acessório, não requisito."""

    def test_job_finishes_even_if_the_row_cannot_be_created(self, pasta, user):
        """Com a linha impossível de criar, `import_job_id` é None e o job roda mesmo assim."""
        with patch.object(import_service.ImportJob.objects, "create", side_effect=Exception("db")):
            with patch.object(
                import_service, "import_candidates_from_folder_no_ranking", return_value={}
            ) as importacao:
                _run_talent_pool_import(pasta, False, user.id, False, None)

        importacao.assert_called_once()
        assert ImportJob.objects.count() == 0

    def test_start_returns_none_instead_of_raising(self, user):
        with patch.object(import_service.ImportJob.objects, "create", side_effect=Exception("db")):
            assert start_import_job(user_id=user.id, kind=ImportJob.Kind.TALENT_POOL_IMPORT) is None

    def test_progress_and_finish_ignore_a_missing_row(self):
        """`None` acontece de verdade: é o que `_start_import_job` devolve quando falha."""
        _track_progress(None, {"processed": 1, "total": 2})
        _finish_import_job(None, status=ImportJob.Status.COMPLETED)

    def test_progress_survives_a_database_error(self, user):
        registro = start_import_job(user_id=user.id, kind=ImportJob.Kind.TALENT_POOL_IMPORT)

        with patch.object(ImportJob.objects, "filter", side_effect=Exception("db caiu")):
            _track_progress(registro, {"processed": 1, "total": 2})


class TestTalentPoolImportIsTracked:
    def test_row_is_created_and_completed(self, pasta, user):
        _roda_talent_pool(pasta, user)

        registro = ImportJob.objects.get()
        assert registro.user_id == user.id
        assert registro.kind == ImportJob.Kind.TALENT_POOL_IMPORT
        assert registro.status == ImportJob.Status.COMPLETED
        assert registro.job_id is None, "importacao do banco de talentos nao pertence a vaga"

    def test_row_records_the_failure(self, pasta, user):
        _roda_talent_pool(pasta, user, erro=RuntimeError("estourou"))

        registro = ImportJob.objects.get()
        assert registro.status == ImportJob.Status.ERROR
        assert "estourou" in registro.error

    def test_o_payload_final_carrega_o_resumo_que_a_tela_mostra(self, pasta, user):
        """R-20b: o que era o payload do cache agora vive na linha, com a mesma forma."""
        _roda_talent_pool(pasta, user, resultado={"created": 2, "updated": 1, "unchanged": 0})

        payload = ImportJob.objects.get().payload
        assert payload["status"] == "completed"
        assert payload["result"]["created"] == 2


class TestProgressIsMirrored:
    def test_processed_and_total_land_in_the_row(self, user):
        registro = start_import_job(user_id=user.id, kind=ImportJob.Kind.TALENT_POOL_IMPORT)

        _track_progress(registro, {"total": 10, "processed": 4, "status": "running"})

        atualizado = ImportJob.objects.get(id=registro)
        assert (atualizado.processed, atualizado.total) == (4, 10)

    def test_heartbeat_moves_forward(self, user):
        registro = start_import_job(user_id=user.id, kind=ImportJob.Kind.TALENT_POOL_IMPORT)
        antes = ImportJob.objects.get(id=registro).heartbeat_at

        _track_progress(registro, {"processed": 1})

        depois = ImportJob.objects.get(id=registro).heartbeat_at
        assert depois >= antes, "e o heartbeat que o R-20b usa para detectar job morto"

    def test_payload_without_counters_is_ignored_gracefully(self, user):
        """O callback final manda `current=None` e `status`, sem contadores."""
        registro = start_import_job(user_id=user.id, kind=ImportJob.Kind.TALENT_POOL_IMPORT)

        _track_progress(registro, {"status": "completed", "current": None})

        assert ImportJob.objects.get(id=registro).processed == 0


class TestVacancyImportIsTracked:
    def test_row_points_at_the_job(self, user):
        vaga = Job.objects.create(user=user, title="Dev Python")

        registro = start_import_job(
            user_id=user.id, kind=ImportJob.Kind.VACANCY_IMPORT, job_id=vaga.id
        )

        assert ImportJob.objects.get(id=registro).job_id == vaga.id

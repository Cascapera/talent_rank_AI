"""Testes da leitura de status vinda do banco (R-20b).

Etapa **contract** do expand-contract: o cache saiu, a leitura passou para a tabela
`ImportJob`, e um job cujo `heartbeat_at` parou de andar deixa de girar "em andamento"
para sempre.

O D-6 na prática: o deploy roda `systemctl restart`, as threads são `daemon` e morrem sem
executar o `finally`. O status ficava `running` no cache por uma hora, e a recrutadora
olhava uma barra parada sem erro em lugar nenhum.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from core.models import ImportJob, Job
from core.services.import_service import (
    _track_progress,
    job_status_payload,
    start_import_job,
)

pytestmark = pytest.mark.django_db

POOL = ImportJob.Kind.TALENT_POOL_IMPORT


def _envelhece(import_job_id, segundos):
    """Recua o heartbeat. `.update()` não dispara `auto_now`, que é o que permite o teste."""
    ImportJob.objects.filter(id=import_job_id).update(
        heartbeat_at=timezone.now() - timedelta(seconds=segundos)
    )


class TestLeituraDoBanco:
    def test_sem_nenhum_job_o_estado_e_idle(self, user):
        assert job_status_payload(user_id=user.id, kind=POOL) == {"status": "idle"}

    def test_job_recente_aparece_em_andamento(self, user):
        job_id = start_import_job(user_id=user.id, kind=POOL, total=10)
        _track_progress(job_id, {"processed": 4, "total": 10})

        payload = job_status_payload(user_id=user.id, kind=POOL)

        assert payload["status"] == "running"
        assert payload["processed"] == 4
        assert payload["total"] == 10

    def test_le_sempre_o_mais_recente(self, user):
        start_import_job(user_id=user.id, kind=POOL, total=1)
        novo = start_import_job(user_id=user.id, kind=POOL, total=99)
        _track_progress(novo, {"processed": 0, "total": 99})

        assert job_status_payload(user_id=user.id, kind=POOL)["total"] == 99


class TestJobQueMorreuNoRestart:
    """O caso que o item existe para resolver."""

    def test_heartbeat_velho_vira_interrompido(self, user):
        job_id = start_import_job(user_id=user.id, kind=POOL, total=10)
        _track_progress(job_id, {"processed": 3, "total": 10})
        _envelhece(job_id, 3600)

        payload = job_status_payload(user_id=user.id, kind=POOL)

        assert payload["status"] == "error"
        assert payload["interrupted"] is True
        assert "reinicie a importação" in payload["message"].lower()

    def test_a_linha_continua_running_no_banco(self, user):
        """A tabela guarda o fato; a interpretação é da leitura.

        Marcar a linha como ERROR exigiria alguém varrendo o banco — e um job que só
        parece morto porque o lote está lento voltaria a andar sozinho.
        """
        job_id = start_import_job(user_id=user.id, kind=POOL, total=10)
        _envelhece(job_id, 3600)

        job_status_payload(user_id=user.id, kind=POOL)

        assert ImportJob.objects.get(id=job_id).status == ImportJob.Status.RUNNING

    def test_job_concluido_nao_vira_interrompido(self, user):
        """Heartbeat velho num job que terminou é só um job antigo."""
        job_id = start_import_job(user_id=user.id, kind=POOL, total=1)
        ImportJob.objects.filter(id=job_id).update(
            status=ImportJob.Status.COMPLETED,
            payload={"status": "completed", "result": {"created": 1}},
        )
        _envelhece(job_id, 86400)

        assert job_status_payload(user_id=user.id, kind=POOL)["status"] == "completed"

    @override_settings(IMPORT_JOB_STALE_AFTER_SECONDS=5)
    def test_o_limiar_vem_das_settings(self, user):
        job_id = start_import_job(user_id=user.id, kind=POOL, total=10)
        _envelhece(job_id, 10)

        assert job_status_payload(user_id=user.id, kind=POOL)["interrupted"] is True

    def test_lote_lento_nao_e_confundido_com_morto(self, user):
        """Um lote de 10 PDFs pode passar 12 minutos sem heartbeat e estar vivo.

        Se este teste falhar porque alguém baixou o limiar, leia o R-12: o timeout do LLM
        é de 180s com até 4 tentativas. Dizer que uma importação viva morreu faz a
        recrutadora reiniciar tudo e pagar o LLM duas vezes.
        """
        job_id = start_import_job(user_id=user.id, kind=POOL, total=10)
        _envelhece(job_id, 13 * 60)

        assert job_status_payload(user_id=user.id, kind=POOL)["status"] == "running"


class TestPeloEndpoint:
    def test_a_tela_da_vaga_recebe_o_interrompido(self, client_logged, user):
        vaga = Job.objects.create(user=user, title="Dev Python")
        job_id = start_import_job(
            user_id=user.id, kind=ImportJob.Kind.VACANCY_IMPORT, job_id=vaga.id, total=5
        )
        _envelhece(job_id, 3600)

        resposta = client_logged.get(f"/vagas/{vaga.id}/import-status/")

        assert resposta.json()["interrupted"] is True

    def test_a_linha_nasce_antes_da_thread(self, client_logged, user):
        """Sem isso o primeiro poll veria `idle` e o JS pararia de pollar.

        É a razão de `start_import_job` ser chamada na view, e não dentro do job.
        """
        import io

        vaga = Job.objects.create(user=user, title="Dev Python")
        pdf = io.BytesIO(b"%PDF-1.4 x")
        pdf.name = "cv.pdf"

        with patch("core.views.threading.Thread"):
            client_logged.post(f"/vagas/{vaga.id}/", {"candidates_zip": pdf})

        resposta = client_logged.get(f"/vagas/{vaga.id}/import-status/")
        assert resposta.json()["status"] == "running", (
            "a thread nem rodou e o poll ja tem que ver a importacao"
        )
        assert resposta.json()["total"] == 1

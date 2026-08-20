"""Etapa 2 do R-31: limpar os PDFs órfãos que o comportamento antigo deixou.

Medido em produção em 2026-08-20: **270 de 719 arquivos, 33M**. O que se apaga aqui são
currículos de pessoas reais, e apagar currículo não se desfaz — por isso o comando move
para quarentena com manifesto em vez de remover, e por isso estes testes se concentram no
que **não** pode ser tocado.

Duas guardas independentes contra o mesmo risco (arquivo gravado antes de a linha existir
no banco): job `RUNNING` com heartbeat vivo aborta o comando, e o corte por `mtime`
preserva o que é recente. São independentes de propósito: a primeira não cobre importação
que morreu no meio, a segunda não cobre lote longo que ainda está rodando.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from core.management.commands.limpar_curriculos_orfaos import (
    _quarentena,
    encontrar_orfaos,
)
from core.models import Candidate, ImportJob
from core.pdf import _save_resume_pdf

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    (tmp_path / "media" / "resumes").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def user(db):
    return User.objects.create_user(username="recrutadora", password="x")


def com_curriculo(user, tmp_path, nome="0001.pdf", conteudo=b"%PDF-1.4 curriculo"):
    candidate = Candidate.objects.create(user=user, name="Ana", linkedin_url=f"x/{nome}")
    origem = tmp_path / nome
    origem.write_bytes(conteudo)
    _save_resume_pdf(candidate, origem)
    return candidate


def orfao_no_disco(media, nome="orfao.pdf", dias_atras=30) -> Path:
    """Arquivo em `resumes/` que nenhuma linha do banco referencia."""
    caminho = media / "media" / "resumes" / "1" / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"%PDF-1.4 abandonado")
    antigo = (timezone.now() - timedelta(days=dias_atras)).timestamp()
    import os

    os.utime(caminho, (antigo, antigo))
    return caminho


class TestOQueNaoPodeSerTocado:
    def test_curriculo_referenciado_nunca_entra_na_lista(self, media, user):
        candidate = com_curriculo(user, media)

        orfaos, _ = encontrar_orfaos(dias=1)

        assert Path(candidate.resume_pdf.path) not in orfaos

    def test_arquivo_recente_e_preservado(self, media):
        """Cobre a janela entre gravar o arquivo e gravar a linha no banco."""
        orfao_no_disco(media, "recem_gravado.pdf", dias_atras=0)

        orfaos, recentes = encontrar_orfaos(dias=1)

        assert orfaos == []
        assert len(recentes) == 1

    def test_importacao_viva_aborta_o_comando(self, media, user):
        orfao_no_disco(media)
        ImportJob.objects.create(
            user=user, kind=ImportJob.Kind.TALENT_POOL_IMPORT, status=ImportJob.Status.RUNNING
        )

        with pytest.raises(CommandError, match="importação"):
            call_command("limpar_curriculos_orfaos", "--mover")

        assert list(_quarentena().rglob("*.pdf")) == []

    def test_job_morto_de_ontem_nao_bloqueia(self, media, user):
        """O `RUNNING` com heartbeat velho é o job que morreu num restart — não conta."""
        orfao_no_disco(media)
        job = ImportJob.objects.create(
            user=user, kind=ImportJob.Kind.TALENT_POOL_IMPORT, status=ImportJob.Status.RUNNING
        )
        ImportJob.objects.filter(pk=job.pk).update(
            heartbeat_at=timezone.now() - timedelta(hours=15)
        )

        call_command("limpar_curriculos_orfaos", "--mover")

        assert len(list(_quarentena().rglob("*.pdf"))) == 1


class TestPadraoSemMover:
    def test_sem_flag_nao_move_nada(self, media):
        caminho = orfao_no_disco(media)

        call_command("limpar_curriculos_orfaos")

        assert caminho.exists()
        assert not _quarentena().exists()


class TestQuarentena:
    def test_move_o_orfao_e_libera_o_media(self, media):
        caminho = orfao_no_disco(media)

        call_command("limpar_curriculos_orfaos", "--mover")

        assert not caminho.exists()
        assert len(list(_quarentena().rglob("*.pdf"))) == 1

    def test_a_quarentena_fica_fora_do_media(self, media):
        """Senão a varredura seguinte acharia os mesmos arquivos de novo."""
        orfao_no_disco(media)

        call_command("limpar_curriculos_orfaos", "--mover")

        assert Path(_quarentena()) not in Path(media / "media").parents
        assert "media" not in _quarentena().parts[-1]

    def test_preserva_a_estrutura_de_pastas(self, media):
        orfao_no_disco(media, "abc.pdf")

        call_command("limpar_curriculos_orfaos", "--mover")

        assert (_quarentena() / "1" / "abc.pdf").is_file()

    def test_escreve_manifesto_com_o_que_moveu(self, media):
        orfao_no_disco(media, "abc.pdf")

        call_command("limpar_curriculos_orfaos", "--mover")

        manifesto = (_quarentena() / "manifesto.csv").read_text(encoding="utf-8")
        assert "origem" in manifesto
        assert "abc.pdf" in manifesto


class TestRestaurar:
    def test_devolve_o_arquivo_para_o_lugar(self, media):
        caminho = orfao_no_disco(media, "abc.pdf")
        conteudo = caminho.read_bytes()
        call_command("limpar_curriculos_orfaos", "--mover")
        assert not caminho.exists()

        call_command("limpar_curriculos_orfaos", "--restaurar")

        assert caminho.is_file()
        assert caminho.read_bytes() == conteudo

    def test_nao_sobrescreve_arquivo_que_voltou_a_existir(self, media):
        """Improvável com uuid no nome, mas o custo do engano é currículo perdido."""
        caminho = orfao_no_disco(media, "abc.pdf")
        call_command("limpar_curriculos_orfaos", "--mover")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"%PDF-1.4 outro arquivo, mesmo nome")

        call_command("limpar_curriculos_orfaos", "--restaurar")

        assert caminho.read_bytes() == b"%PDF-1.4 outro arquivo, mesmo nome"
        assert (_quarentena() / "1" / "abc.pdf").is_file(), "o da quarentena tem de continuar lá"

    def test_restaurar_duas_vezes_nao_reclama_do_que_ja_voltou(self, media):
        orfao_no_disco(media, "abc.pdf")
        call_command("limpar_curriculos_orfaos", "--mover")

        call_command("limpar_curriculos_orfaos", "--restaurar")
        call_command("limpar_curriculos_orfaos", "--restaurar")

        manifesto = (_quarentena() / "manifesto.csv").read_text(encoding="utf-8")
        assert "abc.pdf" not in manifesto

    def test_sem_manifesto_falha_com_mensagem_clara(self, media):
        with pytest.raises(CommandError, match="manifesto"):
            call_command("limpar_curriculos_orfaos", "--restaurar")


class TestCicloCompleto:
    def test_mover_e_restaurar_devolve_o_disco_ao_estado_inicial(self, media, user):
        com_curriculo(user, media)
        orfao_no_disco(media, "a.pdf")
        orfao_no_disco(media, "b.pdf")
        raiz = media / "media" / "resumes"
        antes = sorted(p.relative_to(raiz) for p in raiz.rglob("*") if p.is_file())

        call_command("limpar_curriculos_orfaos", "--mover")
        call_command("limpar_curriculos_orfaos", "--restaurar")

        depois = sorted(p.relative_to(raiz) for p in raiz.rglob("*") if p.is_file())
        assert depois == antes

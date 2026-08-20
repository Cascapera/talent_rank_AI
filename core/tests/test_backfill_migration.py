"""O backfill do R-45 roda de verdade sobre candidatos de verdade.

**Quebrou em produção em 2026-08-20**, no 13º release: a primeira versão fazia
`raiz / candidate.resume_pdf` e num modelo histórico `resume_pdf` ainda é um `FieldFile`,
não a string do caminho — `TypeError: unsupported operand type(s) for /: 'PosixPath' and
'FieldFile'`.

**A suíte inteira estava verde.** O CI roda `migrate` num banco recém-criado, sem nenhum
candidato: o laço do backfill não executava uma única vez. O código era percorrido pelo
`migrate` sem nunca ser exercitado — o mesmo padrão do characterization test do R-05, que
criava o candidato sem currículo e por isso passava dos dois lados da correção.

**Como aplicar:** data migration precisa de teste que crie linhas e chame a função. Sem
isso, `migrate` verde no CI significa apenas "a migration foi importada sem erro de
sintaxe" — não que o que ela faz funciona.
"""

import hashlib
import importlib
from pathlib import Path

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model

from core.models import Candidate
from core.pdf import _save_resume_pdf

pytestmark = pytest.mark.django_db

User = get_user_model()

migration = importlib.import_module("core.migrations.0025_backfill_resume_sha256")

PDF = b"%PDF-1.4 curriculo para backfill"


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return tmp_path


def com_curriculo(user, tmp_path, conteudo=PDF, nome="0001.pdf"):
    candidate = Candidate.objects.create(user=user, name="Ana", linkedin_url=f"x/{nome}")
    origem = tmp_path / nome
    origem.write_bytes(conteudo)
    _save_resume_pdf(candidate, origem)
    return candidate


@pytest.fixture
def user(db):
    return User.objects.create_user(username="recrutadora", password="x")


def zerar_hashes():
    """Simula o estado de quem já estava no banco antes do R-45."""
    Candidate.objects.update(resume_sha256="")


class TestBackfill:
    def test_preenche_o_hash_de_quem_ja_tinha_curriculo(self, media, user):
        candidate = com_curriculo(user, media)
        zerar_hashes()

        migration.preencher(global_apps, None)

        candidate.refresh_from_db()
        assert candidate.resume_sha256 == hashlib.sha256(PDF).hexdigest()

    def test_o_hash_bate_com_o_arquivo_em_disco(self, media, user):
        """Não basta preencher: tem de ser o hash do arquivo certo."""
        candidate = com_curriculo(user, media, conteudo=b"%PDF-1.4 outro conteudo")
        zerar_hashes()

        migration.preencher(global_apps, None)

        candidate.refresh_from_db()
        em_disco = Path(candidate.resume_pdf.path).read_bytes()
        assert candidate.resume_sha256 == hashlib.sha256(em_disco).hexdigest()

    def test_candidato_sem_curriculo_fica_de_fora(self, media, user):
        sem_pdf = Candidate.objects.create(user=user, name="Bruno", linkedin_url="y")

        migration.preencher(global_apps, None)

        sem_pdf.refresh_from_db()
        assert sem_pdf.resume_sha256 == ""

    def test_arquivo_sumido_do_disco_nao_interrompe_o_backfill(self, media, user):
        """`media/` limpo sem limpar o banco não pode derrubar o deploy."""
        sumido = com_curriculo(user, media, nome="0001.pdf")
        Path(sumido.resume_pdf.path).unlink()
        ok = com_curriculo(user, media, conteudo=b"%PDF-1.4 este existe", nome="0002.pdf")
        zerar_hashes()

        migration.preencher(global_apps, None)

        sumido.refresh_from_db()
        ok.refresh_from_db()
        assert sumido.resume_sha256 == ""
        assert len(ok.resume_sha256) == 64

    def test_nao_mexe_em_quem_ja_tem_hash(self, media, user):
        candidate = com_curriculo(user, media)
        Candidate.objects.filter(pk=candidate.pk).update(resume_sha256="ja" * 32)

        migration.preencher(global_apps, None)

        candidate.refresh_from_db()
        assert candidate.resume_sha256 == "ja" * 32

    def test_roda_duas_vezes_sem_mudar_o_resultado(self, media, user):
        candidate = com_curriculo(user, media)
        zerar_hashes()

        migration.preencher(global_apps, None)
        candidate.refresh_from_db()
        primeiro = candidate.resume_sha256

        migration.preencher(global_apps, None)
        candidate.refresh_from_db()

        assert candidate.resume_sha256 == primeiro

    def test_acima_do_tamanho_do_bloco(self, media, user):
        """O `bulk_update` grava de 200 em 200; o resto não pode ficar para trás."""
        for i in range(3):
            com_curriculo(user, media, conteudo=f"%PDF-1.4 numero {i}".encode(), nome=f"{i}.pdf")
        zerar_hashes()

        migration.preencher(global_apps, None)

        assert Candidate.objects.exclude(resume_sha256="").count() == 3


class TestReversao:
    def test_limpar_esvazia_o_campo(self, media, user):
        candidate = com_curriculo(user, media)

        migration.limpar(global_apps, None)

        candidate.refresh_from_db()
        assert candidate.resume_sha256 == ""

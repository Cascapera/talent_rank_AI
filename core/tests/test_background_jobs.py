"""Testes do fechamento de conexão nos jobs de background (R-18).

D-6 do diagnóstico: `close_old_connections` **não existia em lugar nenhum do projeto**.
O Django fecha conexões no sinal `request_finished`, que thread manual não dispara —
então cada importação abria uma conexão Postgres e a deixava aberta para sempre. Elas
acumulam até o banco recusar novas.

O `background_job` resolve num lugar só. Estes testes garantem que ele faz o que promete
e, principalmente, **que as 4 funções de thread estão decoradas** — o esquecimento é o
modo de falha real aqui: alguém adiciona um job novo e não lembra.
"""

from unittest.mock import patch

import pytest

from core.services import import_service
from core.services.import_service import (
    _run_import_job,
    _run_parecer_generation,
    _run_search_in_pool,
    _run_talent_pool_import,
    background_job,
)

JOBS = {
    "_run_import_job": _run_import_job,
    "_run_talent_pool_import": _run_talent_pool_import,
    "_run_search_in_pool": _run_search_in_pool,
    "_run_parecer_generation": _run_parecer_generation,
}


class TestEveryJobIsDecorated:
    """A garantia que mais importa: nenhum job de background escapa."""

    @pytest.mark.parametrize("nome", sorted(JOBS))
    def test_job_is_wrapped(self, nome):
        assert hasattr(JOBS[nome], "__wrapped__"), (
            f"{nome} nao esta decorada com @background_job — vai vazar conexao"
        )

    @pytest.mark.parametrize("nome", sorted(JOBS))
    def test_decoration_keeps_the_name(self, nome):
        """`@wraps` preservado: o mock de `core.views.<job>` nos testes de view depende
        de a função continuar se chamando do mesmo jeito."""
        assert JOBS[nome].__name__ == nome


class TestBackgroundJobDecorator:
    def test_closes_on_entry_and_on_exit(self):
        chamadas = []

        @background_job
        def trabalho():
            chamadas.append("meio")

        with patch.object(import_service, "close_old_connections") as fechar:
            fechar.side_effect = lambda: chamadas.append("fechou")
            trabalho()

        assert chamadas == ["fechou", "meio", "fechou"]

    def test_closes_even_when_the_job_blows_up(self):
        """O caso que importa: é justamente quando o job estoura que a conexão ficaria
        pendurada. O erro continua propagando — o decorator não engole nada."""

        @background_job
        def trabalho():
            raise RuntimeError("estourou")

        with patch.object(import_service, "close_old_connections") as fechar:
            with pytest.raises(RuntimeError, match="estourou"):
                trabalho()

        assert fechar.call_count == 2

    def test_returns_what_the_job_returns(self):
        @background_job
        def trabalho():
            return "resultado"

        with patch.object(import_service, "close_old_connections"):
            assert trabalho() == "resultado"

    def test_passes_arguments_through(self):
        @background_job
        def trabalho(a, b, c=None):
            return (a, b, c)

        with patch.object(import_service, "close_old_connections"):
            assert trabalho(1, 2, c=3) == (1, 2, 3)


@pytest.mark.django_db
class TestRealJobClosesTheConnection:
    def test_talent_pool_import_closes_around_the_work(self, tmp_path, user):
        """Um job de verdade, com o trabalho mockado: confirma que o decorator está no
        caminho e não só definido."""
        pasta = tmp_path / "pdfs"
        pasta.mkdir()

        with (
            patch.object(import_service, "close_old_connections") as fechar,
            patch.object(
                import_service,
                "import_candidates_from_folder_no_ranking",
                return_value={"created": 0, "updated": 0, "total": 0},
            ),
        ):
            _run_talent_pool_import(pasta, False, user.id)

        assert fechar.call_count == 2

    def test_connection_is_closed_even_if_the_import_fails(self, tmp_path, user):
        """A função engole a exceção internamente (grava status de erro), mas a conexão
        tem que ser devolvida do mesmo jeito."""
        pasta = tmp_path / "pdfs"
        pasta.mkdir()

        with (
            patch.object(import_service, "close_old_connections") as fechar,
            patch.object(
                import_service,
                "import_candidates_from_folder_no_ranking",
                side_effect=RuntimeError("falhou"),
            ),
        ):
            _run_talent_pool_import(pasta, False, user.id)

        assert fechar.call_count == 2

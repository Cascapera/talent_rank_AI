"""Testes do indice funcional do lookup de LinkedIn (R-25).

O comportamento das queries nao muda com um indice — o que estes testes travam e a
unica coisa que pode fazer o indice virar peso morto em silencio: ele deixar de casar
com o SQL que o Django gera para `linkedin_url__iexact`.
"""

from importlib import import_module
from unittest.mock import MagicMock, patch

import pytest
from django.db.backends.postgresql.operations import DatabaseOperations
from django.db.migrations.loader import MigrationLoader
from django.db.models.functions import Upper

from core.models import Candidate
from core.services.candidate_import import _find_candidate

INDEX_NAME = "core_candidate_linkedin_upper"


class TestIndiceCasaComOLookup:
    """Sem estes dois, um indice em Lower() passaria no CI e nunca seria usado."""

    def test_iexact_no_postgres_usa_upper(self):
        # django/db/backends/postgresql/operations.py::lookup_cast. Se um upgrade do
        # Django trocar para LOWER, o indice para de ser usado sem nenhum erro — e
        # este teste e o unico aviso.
        assert DatabaseOperations(None).lookup_cast("iexact", "URLField") == "UPPER(%s::text)"

    def test_indice_do_modelo_e_sobre_upper_da_url(self):
        indice = next(i for i in Candidate._meta.indexes if i.name == INDEX_NAME)
        assert len(indice.expressions) == 1
        expressao = indice.expressions[0]
        assert isinstance(expressao, Upper)
        assert expressao.source_expressions[0].name == "linkedin_url"


class TestMigration:
    def test_e_nao_atomica(self):
        """CREATE INDEX CONCURRENTLY nao roda dentro de transacao (P-7)."""
        loader = MigrationLoader(None, load=True)
        migration = loader.disk_migrations[("core", "0022_candidate_linkedin_upper_index")]
        assert migration.atomic is False

    def test_cria_o_indice_esperado(self):
        loader = MigrationLoader(None, load=True)
        migration = loader.disk_migrations[("core", "0022_candidate_linkedin_upper_index")]
        operacoes = [op for op in migration.operations if getattr(op, "index", None)]
        assert len(operacoes) == 1
        assert operacoes[0].index.name == INDEX_NAME
        assert operacoes[0].model_name == "candidate"

    def test_e_no_op_fora_do_postgres(self):
        """A suite roda em SQLite, onde CONCURRENTLY nao existe."""
        operacao = self._operacao()
        schema_editor = MagicMock()
        schema_editor.connection.vendor = "sqlite"

        operacao.database_forwards("core", schema_editor, MagicMock(), MagicMock())
        operacao.database_backwards("core", schema_editor, MagicMock(), MagicMock())

        schema_editor.add_index.assert_not_called()
        schema_editor.remove_index.assert_not_called()

    def test_cria_o_indice_no_postgres(self):
        operacao = self._operacao()
        schema_editor = MagicMock()
        schema_editor.connection.vendor = "postgresql"
        schema_editor.connection.in_atomic_block = False
        estado = MagicMock()
        estado.apps.get_model.return_value = Candidate
        schema_editor.connection.alias = "default"

        with patch("django.db.router.allow_migrate", return_value=True):
            operacao.database_forwards("core", schema_editor, estado, MagicMock())

        schema_editor.add_index.assert_called_once()
        assert schema_editor.add_index.call_args.kwargs["concurrently"] is True

    @staticmethod
    def _operacao():
        modulo = import_module("core.migrations.0022_candidate_linkedin_upper_index")
        return modulo.Migration.operations[0]


@pytest.mark.django_db
class TestBuscaContinuaIgual:
    """O indice nao pode mudar resultado nenhum — so o plano de execucao."""

    def test_acha_ignorando_maiuscula(self, user):
        candidato = Candidate.objects.create(
            user=user, name="Fulano", linkedin_url="https://linkedin.com/in/Fulano"
        )
        achado = _find_candidate(
            "https://LINKEDIN.com/in/FULANO", user_id=user.id, shared_pool=False
        )
        assert achado == candidato

    def test_nao_acha_url_de_outro(self, user):
        Candidate.objects.create(
            user=user, name="Fulano", linkedin_url="https://linkedin.com/in/fulano"
        )
        assert _find_candidate("https://linkedin.com/in/outro", user.id, False) is None

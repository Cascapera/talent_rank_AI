"""Indice funcional para o lookup `linkedin_url__iexact` do upsert (R-25).

Criado com CREATE INDEX CONCURRENTLY: nao trava escrita na tabela, mas nao roda dentro
de transacao — dai o `atomic = False`. Se falhar no meio, o PostgreSQL deixa um indice
INVALID que precisa ser removido a mao antes de nova tentativa (P-7 do
PROJETO_REFATORACAO.md):

    SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE NOT indisvalid;
    DROP INDEX CONCURRENTLY core_candidate_linkedin_upper;

A suite roda em SQLite (talent_query/settings_test.py), onde CONCURRENTLY nao existe —
por isso a operacao vira no-op fora do PostgreSQL, no mesmo espirito da 0018, que so
cria a extensao unaccent no Postgres. O estado das migrations continua igual nos dois
bancos; o que muda e so o plano de execucao das queries.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.models.functions import Upper


class AddIndexConcurrentlyIfPostgres(AddIndexConcurrently):
    """AddIndexConcurrently que nao faz nada fora do PostgreSQL."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY nao pode rodar dentro de transacao.
    atomic = False

    dependencies = [
        ("core", "0021_importjob"),
    ]

    operations = [
        AddIndexConcurrentlyIfPostgres(
            model_name="candidate",
            index=models.Index(Upper("linkedin_url"), name="core_candidate_linkedin_upper"),
        ),
    ]

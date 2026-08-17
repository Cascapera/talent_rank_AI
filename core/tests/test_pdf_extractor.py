"""Testes do pdf_extractor.

O parser de currículo baseado em regex (`parse_candidate_from_pdf` e seus ~23 helpers)
foi removido em R-03: era código inalcançável, substituído pelo caminho LLM.
A cobertura do fluxo vivo — importação em lote, upsert de candidato e ranking — entra
em R-05 e R-06 como characterization tests.
"""

from core.services.candidate_import import (
    import_candidates_from_folder,
    import_candidates_from_folder_no_ranking,
    search_and_rank_candidates_from_pool,
)


class TestPublicApi:
    """Garante que a superfície importada por views.py continua existindo."""

    def test_exposes_the_three_entrypoints_used_by_views(self):
        assert callable(import_candidates_from_folder)
        assert callable(import_candidates_from_folder_no_ranking)
        assert callable(search_and_rank_candidates_from_pool)

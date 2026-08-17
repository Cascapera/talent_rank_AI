"""Testes de `core/domain/normalization.py` e da equivalência exigida pelo R-13.

O R-13 pedia, textualmente: *"Confirme isso com um teste de equivalência ANTES de
unificar. Se divergirem em algum caso, isto vira mudança de comportamento e precisa de
decisão."*

Conferido, e **divergem**. O dicionário de sinônimos era idêntico nas duas cópias e foi
unificado sem risco. As funções de normalização **não** são idênticas — são três
variantes diferentes — então ficaram onde estavam e viraram o **R-36**.

Estes testes existem para que a divergência seja um fato registrado e não uma surpresa
para quem for fazer o R-36.
"""

import pytest

from core import matching, views
from core.domain import normalization
from core.domain.normalization import SYNONYMS, normalize


class TestNormalize:
    """`normalize()` é a variante do `matching`, movida sem alterar uma linha."""

    def test_removes_accents(self):
        assert normalize("Programação") == "programacao"

    def test_lowercases(self):
        assert normalize("PYTHON") == "python"

    def test_strips_the_edges(self):
        assert normalize("  python  ") == "python"

    def test_tolerates_none(self):
        assert normalize(None) == ""

    def test_tolerates_empty(self):
        assert normalize("") == ""

    def test_combines_all_three(self):
        assert normalize("  Ciência de Dados  ") == "ciencia de dados"


class TestSynonymsUnification:
    """O dicionário era idêntico nas duas cópias — esta é a parte segura do R-13."""

    def test_matching_and_views_share_the_very_same_dict(self):
        """Não é "iguais": é o MESMO objeto. É isso que garante que adicionar um
        sinônimo passe a valer nos dois lugares automaticamente, que era o ganho
        prometido pelo item."""
        assert matching.SYNONYMS is normalization.SYNONYMS
        assert views.SYNONYMS is normalization.SYNONYMS

    def test_keys_are_all_ascii(self):
        """Por que isto importa: as duas pontas procuram a chave por caminhos
        ligeiramente diferentes (uma remove acento, a outra não). Enquanto todas as
        chaves forem ASCII, os dois caminhos chegam ao mesmo lugar.

        Se alguém adicionar uma chave acentuada, os dois consumidores passam a
        discordar em silêncio — e aí o R-36 deixa de ser opcional.
        """
        for key in SYNONYMS:
            assert key.isascii(), f"chave não-ASCII em SYNONYMS: {key!r}"

    def test_lookup_works_for_a_known_term(self):
        assert SYNONYMS[normalize("K8s")] == ["kubernetes"]


class TestTheThreeNormalizersDiverge:
    """⚠️ A prova de que as três variantes NÃO produzem a mesma saída.

    O plano supunha que produziam. Não produzem — daí o R-36.
    """

    def test_strip_divergence(self):
        """`normalize` apara as pontas; `views._normalize_term` não.

        Onde isso aparece: `_apply_unaccent_filter` monta um `__contains` com o termo
        já normalizado. Uma recrutadora que digitar " python " com espaço no filtro
        procura literalmente por " python " no campo, em vez de "python".
        """
        assert normalize("  python  ") == "python"
        assert views._normalize_term("  python  ") == "  python  "
        assert normalize("  python  ") != views._normalize_term("  python  ")

    def test_none_divergence(self):
        """`normalize` tolera `None`; `views._normalize_term` estoura."""
        assert normalize(None) == ""

        with pytest.raises(TypeError):
            views._normalize_term(None)

    def test_accent_divergence_in_the_synonym_lookup(self):
        """A chave usada em `expand_term` é `strip().lower()`, sem remover acento.

        Para um termo acentuado, `normalize` acha o sinônimo e `expand_term` não. Hoje
        é inócuo porque ninguém escreve "Reáct" — mas é a mesma classe de bug que o
        R-09 foi: dois caminhos que deveriam concordar e não concordam.
        """
        termo = "Reáct"

        assert normalize(termo) == "react"
        assert normalize(termo) in SYNONYMS

        chave_das_views = termo.strip().lower()
        assert chave_das_views == "reáct"
        assert chave_das_views not in SYNONYMS


class TestMatchingBehaviorUnchanged:
    """R-13 é refatoração: o `matching` tem que se comportar exatamente como antes."""

    def test_term_variants_still_expands_synonyms(self):
        assert set(matching._term_variants("K8s")) == {"k8s", "kubernetes"}

    def test_term_variants_handles_term_without_synonym(self):
        assert matching._term_variants("Django") == ["django"]

    def test_term_variants_normalizes_accents(self):
        assert matching._term_variants("  JAVASCRIPT  ") == ["javascript", "js"]

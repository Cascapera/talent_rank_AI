"""Testes de `core/domain/normalization.py` e da equivalência exigida pelo R-13.

O R-13 pedia, textualmente: *"Confirme isso com um teste de equivalência ANTES de
unificar. Se divergirem em algum caso, isto vira mudança de comportamento e precisa de
decisão."*

Conferido, e **divergiam**. O dicionário de sinônimos era idêntico nas duas cópias e foi
unificado no R-13, sem risco. As funções de normalização eram **três variantes
diferentes**, então ficaram onde estavam e viraram o **R-36**.

O R-36 foi feito em seguida: as três viraram uma. Este arquivo registrava a divergência
caso a caso e agora registra a convergência — de propósito, para que a próxima pessoa
veja que a unificação foi uma decisão testada e não um descuido.
"""

from core import matching, views
from core.domain import boolean_search, normalization
from core.domain.boolean_search import build_boolean_search_from
from core.domain.normalization import SYNONYMS, normalize
from core.models import Job


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

    def test_both_consumers_share_the_very_same_dict(self):
        """Não é "iguais": é o MESMO objeto. É isso que garante que adicionar um
        sinônimo passe a valer nos dois lugares automaticamente, que era o ganho
        prometido pelo R-13.

        O segundo consumidor era `views` até o R-16 mover a busca booleana para
        `domain/boolean_search`. Trocar o alvo aqui é acompanhar a mudança de camada,
        não afrouxar o teste — a afirmação (`is`, não `==`) continua a mesma.
        """
        assert matching.SYNONYMS is normalization.SYNONYMS
        assert boolean_search.SYNONYMS is normalization.SYNONYMS

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


class TestTheThreeNormalizersAreNowOne:
    """R-36: as três variantes viraram uma. Antes divergiam — este arquivo registrava
    a divergência caso a caso, e agora registra a convergência."""

    def test_the_third_variant_no_longer_exists(self):
        """`views._normalize_term` foi deletada; o filtro usa `normalize()`.

        Vale como teste porque é a garantia de que ninguém a reintroduza por hábito.
        """
        assert not hasattr(views, "_normalize_term")

    def test_the_filter_now_strips_the_edges(self):
        """Era a divergência com consequência prática: `_apply_unaccent_filter` monta
        um `__contains` com o termo normalizado. Antes, filtrar por `" python "` com
        espaço sobrando procurava literalmente `" python "` no campo e não achava nada.
        """
        assert normalize("  python  ") == "python"

    def test_the_filter_now_tolerates_none(self):
        """A variante antiga estourava `TypeError` com `None`. Não acontecia na prática
        porque `_apply_unaccent_filter` tem um guarda antes, mas era uma mina."""
        assert normalize(None) == ""

    def test_boolean_search_now_expands_an_accented_synonym(self):
        """A chave de `expand_term` era `strip().lower()`, sem remover acento — então
        um termo acentuado achava o sinônimo no pré-match e não achava na busca
        booleana. Agora os dois saem do mesmo `normalize()`.
        """
        job = Job(
            title="",
            stack="",
            seniority="",
            location="",
            department="",
            must_have="Reáct",
            nice_to_have="",
            undesirable="",
        )

        resultado = build_boolean_search_from(job)

        assert normalize("Reáct") == "react"
        assert "reactjs" in resultado, resultado


class TestMatchingBehaviorUnchanged:
    """R-13 é refatoração: o `matching` tem que se comportar exatamente como antes."""

    def test_term_variants_still_expands_synonyms(self):
        assert set(matching._term_variants("K8s")) == {"k8s", "kubernetes"}

    def test_term_variants_handles_term_without_synonym(self):
        assert matching._term_variants("Django") == ["django"]

    def test_term_variants_normalizes_accents(self):
        assert matching._term_variants("  JAVASCRIPT  ") == ["javascript", "js"]

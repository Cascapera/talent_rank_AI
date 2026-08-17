"""Characterization tests do cliente LLM: retry, parsing e contratos (R-07).

Fixa o comportamento atual de `llm_extractor.py` antes de R-11 extrair o `_generate()`.
Como em R-05 e R-06: estes testes registram o que o sistema faz HOJE, não o que deveria
fazer. Os pontos marcados como QUIRK ficam fixados de propósito — se algum deles for
corrigido, é em PR próprio, marcado como mudança de comportamento.

O alvo do R-11 são as **7 cópias** do trio `api_key` → `genai.Client` → laço de 4
tentativas com backoff [3, 8, 15, 30], uma em cada função pública:

    extract_candidates_batch_with_llm      extract_candidate_with_llm
    extract_candidates_batch_no_ranking    extract_candidate_no_ranking
    calculate_adherence_for_candidate      calculate_adherence_batch_for_candidates
    generate_parecer

**Nenhum teste aqui chama a API do Gemini.** O `genai.Client` é substituído por um duplo
e o `time.sleep` é capturado numa lista — sem isso a suíte dormiria até 56s por teste de
retry esgotado.
"""

from types import SimpleNamespace

import pytest

from core import llm_extractor
from core.llm_extractor import (
    _extract_json,
    _normalize_linkedin_url,
    _normalize_list,
    calculate_adherence_batch_for_candidates,
    calculate_adherence_for_candidate,
    extract_candidate_no_ranking,
    extract_candidate_with_llm,
    extract_candidates_batch_no_ranking,
    extract_candidates_batch_with_llm,
    generate_parecer,
)

WEIGHTS = {"skills": 40, "technologies": 35, "experience": 25}

# Contrato das funções que extraem candidato COM rankeamento (14 chaves).
RANKED_KEYS = {
    "name",
    "linkedin_url",
    "location",
    "current_title",
    "current_company",
    "skills",
    "technologies",
    "languages",
    "certifications",
    "average_tenure_years",
    "experience_time_years",
    "seniority",
    "adherence",
    "technical_justification",
}

# Sem rankeamento: as mesmas menos `adherence` e `technical_justification`.
NO_RANKING_KEYS = RANKED_KEYS - {"adherence", "technical_justification"}


def resp(text):
    """Resposta mínima do SDK: só `.text` é lido pelo código."""
    return SimpleNamespace(text=text)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "cv.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    return path


@pytest.fixture
def llm(monkeypatch):
    """Substitui `genai.Client` e captura os `time.sleep`.

    Devolve um controlador com:
      .responses  — lista de respostas/exceções, consumida em ordem por chamada
      .calls      — kwargs de cada `generate_content`
      .sleeps     — segundos de cada `time.sleep`, na ordem
      .api_key    — a chave que chegou ao construtor do cliente
    """
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")

    ctl = SimpleNamespace(responses=[], calls=[], sleeps=[], api_key=None, http_options=None)

    monkeypatch.setattr(llm_extractor.time, "sleep", ctl.sleeps.append)

    class FakeModels:
        def generate_content(self, **kwargs):
            ctl.calls.append(kwargs)
            item = ctl.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class FakeClient:
        def __init__(self, api_key=None, http_options=None):
            ctl.api_key = api_key
            ctl.http_options = http_options
            self.models = FakeModels()

    monkeypatch.setattr(llm_extractor.genai, "Client", FakeClient)
    return ctl


class TestExtractJson:
    """`_extract_json` faz parsing heurístico: tenta o texto inteiro, depois procura
    um array, depois um objeto. Não usa `response_schema` do Gemini."""

    def test_pure_json_object(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_pure_json_array(self):
        assert _extract_json('[{"a": 1}]') == [{"a": 1}]

    def test_surrounding_whitespace_is_stripped(self):
        assert _extract_json('\n\n  {"a": 1}  \n') == {"a": 1}

    def test_object_wrapped_in_markdown(self):
        assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_array_wrapped_in_markdown(self):
        assert _extract_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]

    def test_garbage_before_and_after_object(self):
        assert _extract_json('Claro! Segue:\n{"a": 1}\nEspero ter ajudado.') == {"a": 1}

    def test_object_with_inner_array_survives_markdown(self):
        """R-35: o candidato não vira mais a lista de skills dele.

        ANTES da correção este mesmo texto devolvia `["Python", "Go"]` — o array era
        procurado antes do objeto, e o recorte do array interno ganhava. Como todo
        candidato tem `skills`, bastava o modelo embrulhar a resposta em markdown uma
        vez para a importação gravar lixo.
        """
        assert _extract_json('```json\n{"skills": ["Python", "Go"]}\n```') == {
            "skills": ["Python", "Go"]
        }

    def test_object_without_inner_array_survives_markdown(self):
        assert _extract_json('```json\n{"name": "Ana"}\n```') == {"name": "Ana"}

    def test_whichever_structure_starts_first_wins(self):
        """A regra que substituiu a ordem fixa: vence quem começa antes no texto.

        É o que mantém o caminho de lote funcionando — a resposta em lote é um array de
        objetos, então o `[` vem antes do primeiro `{` e o array continua ganhando.
        """
        assert _extract_json('```json\n[{"name": "Ana"}]\n```') == [{"name": "Ana"}]
        assert _extract_json('```json\n{"name": "Ana"}\n```') == {"name": "Ana"}

    def test_falls_back_to_the_other_structure_when_the_first_does_not_parse(self):
        """Se o recorte que começa antes não for JSON válido, o outro ainda é tentado."""
        assert _extract_json('nota [rascunho] e o dado: {"name": "Ana"}') == {"name": "Ana"}

    def test_invalid_json_propagates(self):
        import json as _json

        with pytest.raises(_json.JSONDecodeError):
            _extract_json("isso não é json")


class TestNormalizeList:
    def test_none_becomes_empty_list(self):
        assert _normalize_list(None) == []

    def test_list_is_stripped_and_emptied_items_dropped(self):
        assert _normalize_list([" Python ", "", "  ", "Go"]) == ["Python", "Go"]

    def test_comma_separated_string_is_split(self):
        assert _normalize_list("Python, Go , Rust") == ["Python", "Go", "Rust"]

    def test_blank_string_becomes_empty_list(self):
        assert _normalize_list("   ") == []

    def test_other_types_are_wrapped(self):
        assert _normalize_list(42) == ["42"]

    def test_non_string_items_are_coerced(self):
        assert _normalize_list([1, 2]) == ["1", "2"]


class TestNormalizeLinkedinUrl:
    def test_empty_stays_empty(self):
        assert _normalize_linkedin_url("") == ""

    def test_non_linkedin_value_is_only_trimmed(self):
        assert _normalize_linkedin_url("  não informado  ") == "não informado"

    def test_bare_linkedin_url_gets_https(self):
        assert _normalize_linkedin_url("linkedin.com/in/ana") == "https://linkedin.com/in/ana"

    def test_leading_slashes_are_dropped(self):
        assert _normalize_linkedin_url("//linkedin.com/in/ana") == "https://linkedin.com/in/ana"

    def test_url_with_scheme_is_untouched(self):
        assert _normalize_linkedin_url("http://linkedin.com/in/ana") == "http://linkedin.com/in/ana"


class TestApiKeyGuard:
    """As 7 funções checam `GEMINI_API_KEY` antes de qualquer outra coisa e falham
    com a mesma mensagem. É a primeira das 7 duplicações que o R-11 elimina."""

    @pytest.fixture(autouse=True)
    def no_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(
                lambda p: extract_candidates_batch_with_llm([p], "vaga", WEIGHTS),
                id="batch_with_llm",
            ),
            pytest.param(
                lambda p: extract_candidate_with_llm(p, "vaga", WEIGHTS),
                id="candidate_with_llm",
            ),
            pytest.param(
                lambda p: extract_candidates_batch_no_ranking([p]),
                id="batch_no_ranking",
            ),
            pytest.param(
                lambda p: extract_candidate_no_ranking(p),
                id="candidate_no_ranking",
            ),
            pytest.param(
                lambda p: calculate_adherence_for_candidate({}, "vaga", WEIGHTS),
                id="adherence_single",
            ),
            pytest.param(
                lambda p: calculate_adherence_batch_for_candidates([{}], "vaga", WEIGHTS),
                id="adherence_batch",
            ),
            pytest.param(
                lambda p: generate_parecer("vaga", {}, "RESUMIDO", "Dev"),
                id="parecer",
            ),
        ],
    )
    def test_missing_api_key_raises_runtime_error(self, call, pdf):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            call(pdf)


class TestRetry:
    """O laço de 4 tentativas com backoff [3, 8, 15, 30], copiado 7 vezes.

    Usa `extract_candidate_no_ranking` como representante por ser a função mais fina —
    o laço é idêntico nas 7, e `test_all_seven_share_the_same_retry_shape` prova isso.
    """

    def test_success_on_first_attempt_does_not_sleep(self, llm, pdf):
        llm.responses = [resp('{"name": "Ana"}')]

        extract_candidate_no_ranking(pdf)

        assert len(llm.calls) == 1
        assert llm.sleeps == []

    def test_api_key_reaches_the_client(self, llm, pdf):
        llm.responses = [resp('{"name": "Ana"}')]

        extract_candidate_no_ranking(pdf)

        assert llm.api_key == "chave-de-teste"

    def test_default_model_is_used(self, llm, pdf):
        llm.responses = [resp('{"name": "Ana"}')]

        extract_candidate_no_ranking(pdf)

        assert llm.calls[0]["model"] == llm_extractor.DEFAULT_GEMINI_MODEL

    def test_rate_limit_retries_then_succeeds(self, llm, pdf):
        llm.responses = [
            Exception("429 RESOURCE_EXHAUSTED"),
            resp('{"name": "Ana"}'),
        ]

        result = extract_candidate_no_ranking(pdf)

        assert result["name"] == "Ana"
        assert len(llm.calls) == 2
        assert llm.sleeps == [3]

    def test_unavailable_503_retries_then_succeeds(self, llm, pdf):
        llm.responses = [Exception("503 UNAVAILABLE"), resp('{"name": "Ana"}')]

        extract_candidate_no_ranking(pdf)

        assert len(llm.calls) == 2
        assert llm.sleeps == [3]

    def test_backoff_progression_is_3_8_15_30(self, llm, pdf):
        llm.responses = [Exception("429 RESOURCE_EXHAUSTED")] * 4

        with pytest.raises(Exception, match="RESOURCE_EXHAUSTED"):
            extract_candidate_no_ranking(pdf)

        assert len(llm.calls) == 4
        assert llm.sleeps == [3, 8, 15, 30]

    def test_unknown_error_always_sleeps_three_seconds(self, llm, pdf):
        """Erro que não é rate limit nem indisponibilidade não usa o backoff:
        dorme 3s fixos, e mesmo assim tenta as 4 vezes."""
        llm.responses = [Exception("boom")] * 4

        with pytest.raises(Exception, match="boom"):
            extract_candidate_no_ranking(pdf)

        assert len(llm.calls) == 4
        assert llm.sleeps == [3, 3, 3, 3]

    def test_sleeps_after_the_last_attempt_before_giving_up(self, llm, pdf):
        """QUIRK: o laço dorme DEPOIS da 4ª tentativa também, antes de propagar o erro.

        Com rate limit, isso são 30s parados sem nenhuma tentativa pela frente — a
        importação simplesmente demora 30s a mais para falhar. Fixado aqui; o R-11 é
        que decide se o laço extraído mantém isso.
        """
        llm.responses = [Exception("429 RESOURCE_EXHAUSTED")] * 4

        with pytest.raises(Exception, match="RESOURCE_EXHAUSTED"):
            extract_candidate_no_ranking(pdf)

        assert len(llm.sleeps) == len(llm.calls) == 4
        assert llm.sleeps[-1] == 30

    def test_last_error_is_the_one_propagated(self, llm, pdf):
        llm.responses = [
            Exception("primeiro"),
            Exception("segundo"),
            Exception("terceiro"),
            Exception("ultimo"),
        ]

        with pytest.raises(Exception, match="ultimo"):
            extract_candidate_no_ranking(pdf)


class TestTimeout:
    """R-12: toda chamada ao LLM passa a ter timeout, aplicado no `_generate()`.

    Antes, uma requisição travada segurava a thread de importação para sempre — as
    threads são `daemon` e não têm cancelamento, então a barra de progresso ficava
    parada até o próximo restart do serviço.
    """

    def test_timeout_is_sent_to_the_sdk(self, llm, pdf, settings):
        settings.LLM_TIMEOUT_SECONDS = 180
        llm.responses = [resp('{"name": "Ana"}')]

        extract_candidate_no_ranking(pdf)

        assert llm.http_options is not None
        assert llm.http_options.timeout == 180_000

    def test_timeout_is_converted_from_seconds_to_milliseconds(self, llm, pdf, settings):
        """O setting é em SEGUNDOS porque é o que faz sentido para quem configura; o
        SDK recebe MILISSEGUNDOS (`HttpOptions.timeout` é documentado assim).

        Este teste existe para travar a conversão: passar o valor direto daria 180ms e
        derrubaria toda chamada ao LLM em produção.
        """
        settings.LLM_TIMEOUT_SECONDS = 42
        llm.responses = [resp("{}")]

        extract_candidate_no_ranking(pdf)

        assert llm.http_options.timeout == 42_000

    def test_timeout_error_is_retried_like_any_other_and_then_propagates(self, llm, pdf):
        """O erro de timeout do SDK não casa com RESOURCE_EXHAUSTED nem com 503, então
        cai no ramo genérico: dorme 3s fixos e consome as 4 tentativas.

        Consequência a olhar de frente: com o default de 180s, uma indisponibilidade
        prolongada leva ~12min (4 × 180s + sleeps) para desistir. É **limitado**, que é
        o ganho real do R-12 — antes era para sempre —, mas não é curto.
        """
        llm.responses = [TimeoutError("deadline exceeded")] * 4

        with pytest.raises(TimeoutError, match="deadline exceeded"):
            extract_candidate_no_ranking(pdf)

        assert len(llm.calls) == 4
        assert llm.sleeps == [3, 3, 3, 3]


class TestContracts:
    """Formato exato devolvido por cada uma das 7 funções públicas, com o LLM mockado.

    É o que o R-11 precisa preservar: a extração do `_generate()` não pode mudar
    nenhuma chave nem nenhum tipo.
    """

    def test_batch_with_llm_returns_ranked_dicts(self, llm, pdf):
        llm.responses = [resp('[{"name": "Ana", "skills": ["Python"], "adherence": 80}]')]

        results = extract_candidates_batch_with_llm([pdf], "vaga", WEIGHTS)

        assert len(results) == 1
        assert set(results[0]) == RANKED_KEYS
        assert results[0]["name"] == "Ana"
        assert results[0]["skills"] == ["Python"]
        assert results[0]["adherence"] == 80

    def test_candidate_with_llm_returns_ranked_dict(self, llm, pdf):
        llm.responses = [resp('{"name": "Ana", "adherence": 90}')]

        result = extract_candidate_with_llm(pdf, "vaga", WEIGHTS)

        assert set(result) == RANKED_KEYS
        assert result["adherence"] == 90

    def test_batch_no_ranking_omits_adherence(self, llm, pdf):
        llm.responses = [resp('[{"name": "Ana"}]')]

        results = extract_candidates_batch_no_ranking([pdf])

        assert set(results[0]) == NO_RANKING_KEYS
        assert "adherence" not in results[0]

    def test_candidate_no_ranking_omits_adherence(self, llm, pdf):
        llm.responses = [resp('{"name": "Ana"}')]

        result = extract_candidate_no_ranking(pdf)

        assert set(result) == NO_RANKING_KEYS

    def test_adherence_single_returns_two_keys(self, llm):
        llm.responses = [resp('{"adherence": 75, "technical_justification": "boa"}')]

        result = calculate_adherence_for_candidate({"name": "Ana"}, "vaga", WEIGHTS)

        assert result == {"adherence": 75, "technical_justification": "boa"}

    def test_adherence_batch_returns_one_dict_per_candidate(self, llm):
        llm.responses = [
            resp(
                '[{"adherence": 70, "technical_justification": "a"}, '
                '{"adherence": 60, "technical_justification": "b"}]'
            )
        ]

        results = calculate_adherence_batch_for_candidates(
            [{"name": "Ana"}, {"name": "Bia"}], "vaga", WEIGHTS
        )

        assert results == [
            {"adherence": 70, "technical_justification": "a"},
            {"adherence": 60, "technical_justification": "b"},
        ]

    def test_parecer_returns_stripped_text(self, llm):
        llm.responses = [resp("  Parecer do candidato.  \n")]

        result = generate_parecer("vaga", {"name": "Ana"}, "RESUMIDO", "Dev")

        assert result == "Parecer do candidato."

    def test_parecer_with_empty_response_returns_empty_string(self, llm):
        llm.responses = [resp(None)]

        assert generate_parecer("vaga", {}, "RESUMIDO", "Dev") == ""

    def test_missing_fields_become_empty_string_not_none(self, llm, pdf):
        """Todo campo de texto ausente vira `""`, nunca `None` — é o que permite ao
        `_upsert_candidate` comparar com o que está no banco sem tratar `None`."""
        llm.responses = [resp("{}")]

        result = extract_candidate_no_ranking(pdf)

        assert result["name"] == ""
        assert result["location"] == ""
        assert result["seniority"] == ""
        assert result["skills"] == []

    def test_numeric_fields_stay_none_when_absent(self, llm, pdf):
        """QUIRK: os numéricos NÃO seguem a regra acima — ficam `None`, não 0.
        É proposital: `experience_time` é `null=True` no banco, e 0 anos de experiência
        significa outra coisa que "não informado"."""
        llm.responses = [resp("{}")]

        result = extract_candidate_no_ranking(pdf)

        assert result["experience_time_years"] is None
        assert result["average_tenure_years"] is None

    def test_linkedin_url_is_normalized_on_the_way_out(self, llm, pdf):
        llm.responses = [resp('{"linkedin_url": "linkedin.com/in/ana"}')]

        result = extract_candidate_no_ranking(pdf)

        assert result["linkedin_url"] == "https://linkedin.com/in/ana"


class TestBatchSizeMismatch:
    """Os três fluxos em lote exigem que o LLM devolva exatamente um resultado por
    item enviado. É essa exceção que faz o `_process_in_batches` cair no fallback
    individual — o caminho que o bug do R-09 vivia."""

    def test_fewer_results_than_pdfs_raises(self, llm, pdf, tmp_path):
        outro = tmp_path / "outro.pdf"
        outro.write_bytes(b"%PDF-1.4 fake")
        llm.responses = [resp('[{"name": "Ana"}]')]

        with pytest.raises(RuntimeError, match="1 resultado"):
            extract_candidates_batch_no_ranking([pdf, outro])

    def test_single_object_is_wrapped_in_a_list(self, llm, pdf):
        """Objeto solto vira lista de 1 — só passa na validação com 1 PDF enviado."""
        llm.responses = [resp('{"name": "Ana"}')]

        results = extract_candidates_batch_no_ranking([pdf])

        assert len(results) == 1
        assert results[0]["name"] == "Ana"

    def test_adherence_batch_also_validates_the_count(self, llm):
        llm.responses = [resp('[{"adherence": 70}]')]

        with pytest.raises(RuntimeError, match="1 resultado"):
            calculate_adherence_batch_for_candidates(
                [{"name": "Ana"}, {"name": "Bia"}], "vaga", WEIGHTS
            )

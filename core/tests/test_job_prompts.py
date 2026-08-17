"""Golden tests da descrição da vaga e da busca booleana (R-16).

**A string produzida é contrato.** A descrição vai direto no prompt do LLM: mudar uma
palavra, uma ordem ou um `-` muda o resultado do ranking de todos os candidatos. A busca
booleana é o texto que a recrutadora cola no LinkedIn Recruiter.

Os valores esperados abaixo foram **capturados da implementação antiga**, quando as duas
funções ainda moravam em `views.py`, e colados aqui literalmente. É o que prova que a
mudança de camada não mexeu em um byte.

Rodam **sem banco e sem HTTP** — nem `django_db`, nem client. É o ponto de mover para
`domain/`: a regra passa a ser testável sozinha.
"""

from types import SimpleNamespace

from core.domain.boolean_search import build_boolean_search, build_boolean_search_from
from core.domain.job_description import build_job_description, build_job_description_from

VAGA_COMPLETA = {
    "title": "Desenvolvedor Backend",
    "summary": "Time de plataforma",
    "seniority": "Senior",
    "location": "São Paulo",
    "stack": "Python",
    "department": "Tecnologia",
    "contract_type": "CLT",
    "language": "Inglês",
    "must_have": "Django, K8s",
    "nice_to_have": "React, AWS",
    "undesirable": "PHP",
    "notes": "Remoto 2x",
}

VAGA_VAZIA = dict.fromkeys(VAGA_COMPLETA, "") | {"title": "Dev"}

# --- capturados da implementação de views.py, antes do R-16 ---

DESCRICAO_COMPLETA = (
    "Título: Desenvolvedor Backend\n"
    "Resumo: Time de plataforma\n"
    "Senioridade: Senior\n"
    "Localização: São Paulo\n"
    "Stack: Python\n"
    "Tipo de contratação: CLT\n"
    "Idioma: Inglês\n"
    "Skills obrigatórias: Django, K8s\n"
    "Skills desejáveis: React, AWS\n"
    "Não desejáveis: PHP\n"
    "Observações: Remoto 2x"
)

DESCRICAO_VAZIA = (
    "Título: Dev\n"
    "Resumo: -\n"
    "Senioridade: -\n"
    "Localização: -\n"
    "Stack: -\n"
    "Tipo de contratação: -\n"
    "Idioma: -\n"
    "Skills obrigatórias: -\n"
    "Skills desejáveis: -\n"
    "Não desejáveis: -\n"
    "Observações: -"
)

BUSCA_COMPLETA = (
    '"Desenvolvedor Backend" AND "Python" AND "Senior" AND "São Paulo" AND "Tecnologia" '
    'AND "Django" AND ("K8s" OR "kubernetes") '
    'AND (("React" OR "reactjs") OR ("AWS" OR "amazon web services")) '
    'AND NOT ("PHP")'
)

BUSCA_VAZIA = '"Dev"'


def _sem_department(campos: dict) -> dict:
    """`build_job_description` não recebe `department` — só a busca booleana usa."""
    return {k: v for k, v in campos.items() if k != "department"}


def _campos_da_busca(campos: dict) -> dict:
    usados = (
        "title",
        "stack",
        "seniority",
        "location",
        "department",
        "must_have",
        "nice_to_have",
        "undesirable",
    )
    return {k: campos[k] for k in usados}


class TestJobDescription:
    def test_full_job_matches_the_golden_byte_for_byte(self):
        assert build_job_description(**_sem_department(VAGA_COMPLETA)) == DESCRICAO_COMPLETA

    def test_empty_fields_become_dashes(self):
        assert build_job_description(**_sem_department(VAGA_VAZIA)) == DESCRICAO_VAZIA

    def test_adapter_produces_the_same_string(self):
        """O atalho que lê atributos tem que dar exatamente o mesmo resultado."""
        vaga = SimpleNamespace(**VAGA_COMPLETA)

        assert build_job_description_from(vaga) == DESCRICAO_COMPLETA

    def test_works_without_django(self):
        """Nem `django_db`, nem client, nem objeto do ORM — só um `SimpleNamespace`.

        É o ponto de ter movido para `domain/`: antes, testar isto exigia subir uma
        request HTTP.
        """
        vaga = SimpleNamespace(**VAGA_VAZIA)

        assert build_job_description_from(vaga) == DESCRICAO_VAZIA


class TestBooleanSearch:
    def test_full_job_matches_the_golden_byte_for_byte(self):
        assert build_boolean_search(**_campos_da_busca(VAGA_COMPLETA)) == BUSCA_COMPLETA

    def test_only_the_title_produces_a_single_quoted_term(self):
        assert build_boolean_search(**_campos_da_busca(VAGA_VAZIA)) == BUSCA_VAZIA

    def test_adapter_produces_the_same_string(self):
        vaga = SimpleNamespace(**VAGA_COMPLETA)

        assert build_boolean_search_from(vaga) == BUSCA_COMPLETA

    def test_synonyms_are_expanded(self):
        """`K8s` vira `("K8s" OR "kubernetes")` — o dicionário unificado no R-13."""
        resultado = build_boolean_search(title="", must_have="K8s")

        assert resultado == '("K8s" OR "kubernetes")'

    def test_must_have_terms_are_joined_with_and(self):
        resultado = build_boolean_search(title="", must_have="Django, Flask")

        assert resultado == '"Django" AND "Flask"'

    def test_nice_to_have_terms_are_joined_with_or(self):
        resultado = build_boolean_search(title="", nice_to_have="Django, Flask")

        assert resultado == '("Django" OR "Flask")'

    def test_undesirable_terms_go_into_a_not_group(self):
        resultado = build_boolean_search(title="", undesirable="PHP, Delphi")

        assert resultado == 'NOT ("PHP" OR "Delphi")'

    def test_everything_empty_produces_an_empty_string(self):
        assert build_boolean_search() == ""

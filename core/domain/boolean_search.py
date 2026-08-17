"""Geração da string de busca booleana da vaga (R-16).

É o texto que a recrutadora cola no LinkedIn Recruiter. Sai de `views.py`, onde estava
misturado com HTTP, para poder ser testado sem subir uma request.

Este módulo não importa Django.
"""

from .normalization import SYNONYMS, normalize


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _expand_term(term: str) -> list[str]:
    """Termo + seus sinônimos.

    A chave sai do mesmo `normalize()` que o pré-match usa (R-36). Antes era
    `strip().lower()`, sem remover acento, e as duas pontas divergiam em silêncio.
    """
    return [term] + SYNONYMS.get(normalize(term), [])


def _group_terms(terms: list[str]) -> str:
    expanded = []
    for term in terms:
        expanded.extend(_expand_term(term))
    expanded = [t for t in expanded if t]
    if not expanded:
        return ""
    if len(expanded) == 1:
        return f'"{expanded[0]}"'
    return "(" + " OR ".join(f'"{t}"' for t in expanded) + ")"


def build_boolean_search(
    *,
    title: str = "",
    stack: str = "",
    seniority: str = "",
    location: str = "",
    department: str = "",
    must_have: str = "",
    nice_to_have: str = "",
    undesirable: str = "",
) -> str:
    """Monta a busca booleana.

    Termos-base entram com `AND`; obrigatórias com `AND`; desejáveis num grupo `OR`;
    indesejáveis num `NOT (...)`. Cada termo é expandido com seus sinônimos.
    """
    parts = []
    for base_term in [title, stack, seniority, location, department]:
        if base_term:
            parts.append(_group_terms([base_term]))

    must = _split_terms(must_have)
    if must:
        parts.append(" AND ".join(_group_terms([item]) for item in must if item))

    nice = _split_terms(nice_to_have)
    if nice:
        nice_groups = [_group_terms([item]) for item in nice if item]
        nice_groups = [g for g in nice_groups if g]
        if nice_groups:
            parts.append("(" + " OR ".join(nice_groups) + ")")

    nao_desejadas = _split_terms(undesirable)
    if nao_desejadas:
        not_groups = [_group_terms([item]) for item in nao_desejadas if item]
        not_groups = [g for g in not_groups if g]
        if not_groups:
            parts.append("NOT (" + " OR ".join(not_groups) + ")")

    parts = [p for p in parts if p]
    return " AND ".join(parts).strip()


def build_boolean_search_from(job) -> str:
    """Atalho para quem já tem o objeto da vaga. Só lê atributos — ver
    `job_description.build_job_description_from` para o raciocínio."""
    return build_boolean_search(
        title=job.title,
        stack=job.stack,
        seniority=job.seniority,
        location=job.location,
        department=job.department,
        must_have=job.must_have,
        nice_to_have=job.nice_to_have,
        undesirable=job.undesirable,
    )

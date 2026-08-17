"""Descrição da vaga em texto, do jeito que o LLM recebe (R-16).

⚠️ **A string produzida é contrato.** Ela vai direto no prompt: mudar uma palavra, uma
ordem ou um `-` muda o resultado do ranking de todos os candidatos. `test_job_prompts.py`
compara byte a byte com a saída de antes da mudança de camada.

Este módulo não importa Django. É o que permite testá-lo sem banco e sem HTTP.
"""


def build_job_description(
    *,
    title: str,
    summary: str = "",
    seniority: str = "",
    location: str = "",
    stack: str = "",
    contract_type: str = "",
    language: str = "",
    must_have: str = "",
    nice_to_have: str = "",
    undesirable: str = "",
    notes: str = "",
) -> str:
    """Monta a descrição textual da vaga. Campo vazio vira `-`."""
    parts = [
        f"Título: {title}",
        f"Resumo: {summary or '-'}",
        f"Senioridade: {seniority or '-'}",
        f"Localização: {location or '-'}",
        f"Stack: {stack or '-'}",
        f"Tipo de contratação: {contract_type or '-'}",
        f"Idioma: {language or '-'}",
        f"Skills obrigatórias: {must_have or '-'}",
        f"Skills desejáveis: {nice_to_have or '-'}",
        f"Não desejáveis: {undesirable or '-'}",
        f"Observações: {notes or '-'}",
    ]
    return "\n".join(parts)


def build_job_description_from(job) -> str:
    """Atalho para quem já tem o objeto da vaga em mãos.

    Só **lê atributos** — não importa o ORM nem depende dele. Qualquer objeto com esses
    campos serve, o que mantém o módulo testável com um `SimpleNamespace`. A função de
    contrato é a `build_job_description` acima; esta é conveniência de chamador.
    """
    return build_job_description(
        title=job.title,
        summary=job.summary,
        seniority=job.seniority,
        location=job.location,
        stack=job.stack,
        contract_type=job.contract_type,
        language=job.language,
        must_have=job.must_have,
        nice_to_have=job.nice_to_have,
        undesirable=job.undesirable,
        notes=job.notes,
    )

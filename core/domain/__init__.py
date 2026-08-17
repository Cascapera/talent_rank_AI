"""Regra de negócio pura: NÃO importa Django, ORM, settings nem forms.

É o que torna esta camada testável sem banco, sem HTTP e sem chave de API. A regra de
dependência do projeto (seção 5 do PROJETO_REFATORACAO.md) é:

    views  ->  services  ->  domain
                         ->  llm
                         ->  models (ORM)

    llm    ->  domain          (nunca o contrário)
    domain ->  NADA do Django

As setas só apontam para baixo. Se um módulo daqui precisar importar Django, ele está
no lugar errado.
"""

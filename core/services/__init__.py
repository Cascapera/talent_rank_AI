"""Camada de serviço: orquestração dos casos de uso.

Conhece o ORM e coordena o trabalho; **não** conhece `request` nem `response`. É a
camada entre as views (HTTP) e o domínio (regra pura).

Regra de dependência do projeto (seção 5 do PROJETO_REFATORACAO.md):

    views  ->  services  ->  domain
                         ->  llm
                         ->  models (ORM)

As setas só apontam para baixo. Se um módulo daqui precisar importar `views`, ou o
recorte está errado ou falta mover algo para `domain/`.
"""

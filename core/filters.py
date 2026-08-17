"""Coleta de filtros de listagem e montagem da querystring de paginação (R-15).

`job_detail` e `talent_pool` repetiam o mesmo bloco de ~55 linhas: ler cada parâmetro do
querystring, aparar as pontas, montar o dicionário que o template usa para repreencher o
formulário e remontar a querystring que preserva os filtros ao paginar.

Cada view declara só os campos; a mecânica mora aqui.
"""

from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass(frozen=True)
class Filters:
    """O que `collect_filters` devolve.

    `values` tem **todos** os parâmetros declarados, inclusive os vazios — é o que o
    template usa para repreencher os campos. `query_string` tem só os preenchidos.
    """

    values: dict[str, str]
    query_string: str

    def __getitem__(self, param: str) -> str:
        return self.values[param]


def collect_filters(request, params) -> Filters:
    """Lê `params` do querystring, apara as pontas e monta a string de paginação.

    ⚠️ A `query_string` sai **com `&` na frente** quando não está vazia, porque o
    template a cola logo depois de `?page=N`. Sem o `&`, o link de paginação vira
    `?page=2name=Ana` e a busca se perde ao virar de página. Fixado por
    `test_querystring_keeps_the_filters_and_starts_with_an_ampersand` (R-38).

    A ordem dos parâmetros na URL é a ordem de `params`: dicionário do Python preserva
    inserção. Reordenar a declaração muda a URL que a usuária vê e compartilha.
    """
    values = {param: request.GET.get(param, "").strip() for param in params}
    preenchidos = {param: valor for param, valor in values.items() if valor}
    query_string = urlencode(preenchidos)
    return Filters(
        values=values,
        query_string=f"&{query_string}" if query_string else "",
    )

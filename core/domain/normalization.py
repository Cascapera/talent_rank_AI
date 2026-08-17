"""Normalização de termos e dicionário de sinônimos (R-13).

Antes deste módulo, o dicionário de sinônimos existia em **duas cópias idênticas** —
`matching.SYNONYMS` e um dict local dentro de `views._build_boolean_search`. Adicionar
um sinônimo (ex.: "postgres" -> "postgresql") exigia lembrar dos dois lugares, e valia
só onde fosse lembrado: o pré-match e a busca booleana passariam a discordar em
silêncio.

⚠️ **A normalização NÃO foi unificada neste item, de propósito.** Existem três variantes
no código e elas **não** produzem a mesma saída — ao contrário do que o plano supunha.
`test_normalization.py` prova a divergência termo a termo. Unificá-las é mudança de
comportamento e virou item próprio (**R-36**).
"""

import unicodedata

# Sinônimos de tecnologia usados tanto pelo pré-match (matching.py) quanto pela geração
# da busca booleana (views._build_boolean_search). As chaves são todas ASCII, o que é o
# que permite os dois chamadores procurarem por caminhos ligeiramente diferentes sem
# divergir na prática — ver R-36.
SYNONYMS = {
    "js": ["javascript"],
    "javascript": ["js"],
    "node": ["node.js", "nodejs"],
    "nodejs": ["node.js", "node"],
    "node.js": ["node", "nodejs"],
    "react": ["reactjs"],
    "reactjs": ["react"],
    "k8s": ["kubernetes"],
    "kubernetes": ["k8s"],
    "aws": ["amazon web services"],
    "gcp": ["google cloud"],
    "ci/cd": ["cicd", "continuous integration", "continuous delivery"],
}


def normalize(value: str) -> str:
    """Remove acento, baixa a caixa e apara as pontas. Tolera `None`.

    É a variante do `matching`, movida sem alterar uma linha. As outras duas variantes
    do código (`views._normalize_term`, sem `strip` e sem tolerar `None`; e a chave de
    `expand_term`, que nem remove acento) continuam onde estão até o R-36 decidir.
    """
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower().strip()

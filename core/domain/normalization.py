"""Normalização de termos e dicionário de sinônimos (R-13).

Antes deste módulo, o dicionário de sinônimos existia em **duas cópias idênticas** —
`matching.SYNONYMS` e um dict local dentro de `views._build_boolean_search`. Adicionar
um sinônimo (ex.: "postgres" -> "postgresql") exigia lembrar dos dois lugares, e valia
só onde fosse lembrado: o pré-match e a busca booleana passariam a discordar em
silêncio.

A normalização não foi unificada junto, de propósito: existiam **três** variantes que
**não** produziam a mesma saída, ao contrário do que o plano supunha. Virou o **R-36**,
feito em seguida — hoje `normalize()` é a única, usada pelo pré-match, pelo filtro das
listagens e pela busca booleana.
"""

import unicodedata

# Sinônimos de tecnologia usados tanto pelo pré-match (matching.py) quanto pela geração
# da busca booleana (views._build_boolean_search). Desde o R-36 os dois procuram a chave
# pelo mesmo `normalize()`, então uma chave acentuada aqui passou a ser segura — antes
# faria os dois consumidores discordarem em silêncio.
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

    Única normalização de termo do sistema (R-36). Usada pelo pré-match (`matching`),
    pelo filtro com `unaccent` das listagens (`views._apply_unaccent_filter`) e pela
    busca booleana (`views._build_boolean_search`).

    Era a variante do `matching`; as outras duas foram deletadas. A que valia no filtro
    não aparava as pontas — filtrar por `" python "` procurava literalmente `" python "`
    no campo e não achava nada.
    """
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower().strip()

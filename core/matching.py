"""
Pré-match entre vaga e candidatos do banco de talentos.

Calcula um score de 0 a 100 comparando os requisitos da vaga (skills
obrigatórias, stack, skills desejáveis, senioridade e idioma) com os dados
salvos do candidato, sem chamar a LLM. Apenas candidatos com score igual ou
acima do mínimo seguem para a avaliação final via LLM (PDF do currículo
quando disponível, dados estruturados caso contrário).
"""

from django.conf import settings

from .domain.normalization import SYNONYMS, normalize

# Pesos por categoria. Categorias não preenchidas na vaga são desconsideradas
# e o score é normalizado pelos pesos das categorias restantes.
CATEGORY_WEIGHTS = {
    "must_have": 50,
    "stack": 20,
    "nice_to_have": 15,
    "seniority": 10,
    "language": 5,
}

DEFAULT_MIN_MATCH_SCORE = 40

# Escada de senioridade: candidato com nível igual ou acima atende a vaga.
SENIORITY_LADDER = {
    "trainee": 0,
    "estagiario": 0,
    "junior": 1,
    "pleno": 2,
    "senior": 3,
    "especialista": 4,
    "staff": 4,
    "principal": 4,
}


def get_min_match_score() -> int:
    return getattr(settings, "POOL_MATCH_MIN_SCORE", DEFAULT_MIN_MATCH_SCORE)


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _term_variants(term: str) -> list[str]:
    normalized = normalize(term)
    variants = [normalized] + [normalize(s) for s in SYNONYMS.get(normalized, [])]
    return [v for v in variants if v]


def _term_in_haystack(term: str, haystack: str) -> bool:
    return any(variant in haystack for variant in _term_variants(term))


def _match_ratio(terms: list[str], haystack: str) -> tuple[float, list[str]]:
    matched = [term for term in terms if _term_in_haystack(term, haystack)]
    return len(matched) / len(terms), matched


def _seniority_rank(value: str) -> int | None:
    normalized = normalize(value)
    for label, rank in SENIORITY_LADDER.items():
        if label in normalized:
            return rank
    return None


def _seniority_matches(job_seniority: str, candidate_seniority: str) -> bool:
    job_rank = _seniority_rank(job_seniority)
    candidate_rank = _seniority_rank(candidate_seniority)
    if job_rank is not None and candidate_rank is not None:
        return candidate_rank >= job_rank
    job_norm = normalize(job_seniority)
    candidate_norm = normalize(candidate_seniority)
    if not job_norm or not candidate_norm:
        return False
    return job_norm in candidate_norm or candidate_norm in job_norm


def job_has_match_criteria(job) -> bool:
    """True se a vaga tem ao menos um campo usável para o pré-match."""
    return bool(
        _split_terms(job.must_have)
        or _split_terms(job.stack)
        or _split_terms(job.nice_to_have)
        or (job.seniority or "").strip()
        or (job.language or "").strip()
    )


def compute_match(job, candidate) -> dict:
    """
    Calcula o match entre uma vaga e um candidato.

    Retorna {"score": int 0-100, "matched_terms": [str]}.
    """
    haystack = normalize(
        " | ".join(
            [
                candidate.current_title or "",
                candidate.skills or "",
                candidate.technologies or "",
                candidate.certifications or "",
                candidate.summary or "",
            ]
        )
    )

    fractions: dict[str, float] = {}
    matched_terms: list[str] = []

    must_have = _split_terms(job.must_have)
    if must_have:
        fraction, matched = _match_ratio(must_have, haystack)
        fractions["must_have"] = fraction
        matched_terms.extend(matched)

    stack = _split_terms(job.stack)
    if stack:
        fraction, matched = _match_ratio(stack, haystack)
        fractions["stack"] = fraction
        matched_terms.extend(matched)

    nice_to_have = _split_terms(job.nice_to_have)
    if nice_to_have:
        fraction, matched = _match_ratio(nice_to_have, haystack)
        fractions["nice_to_have"] = fraction
        matched_terms.extend(matched)

    if (job.seniority or "").strip():
        matches = _seniority_matches(job.seniority, candidate.seniority or "")
        fractions["seniority"] = 1.0 if matches else 0.0
        if matches:
            matched_terms.append(job.seniority.strip())

    if (job.language or "").strip():
        languages_haystack = normalize(candidate.languages or "")
        job_languages = _split_terms(job.language)
        fraction, matched = _match_ratio(job_languages, languages_haystack)
        fractions["language"] = fraction
        matched_terms.extend(matched)

    total_weight = sum(CATEGORY_WEIGHTS[category] for category in fractions)
    if total_weight == 0:
        return {"score": 0, "matched_terms": []}

    weighted = sum(
        fraction * CATEGORY_WEIGHTS[category] for category, fraction in fractions.items()
    )
    score = round(weighted / total_weight * 100)

    # Remove duplicados preservando ordem
    seen = set()
    unique_terms = []
    for term in matched_terms:
        key = normalize(term)
        if key not in seen:
            seen.add(key)
            unique_terms.append(term)

    return {"score": score, "matched_terms": unique_terms}


def match_candidates_for_job(job, candidates, min_score: int | None = None) -> list[dict]:
    """
    Aplica o pré-match a um queryset/lista de candidatos.

    Retorna lista de {"candidate", "score", "matched_terms"} com score >= mínimo,
    ordenada por score decrescente.
    """
    if min_score is None:
        min_score = get_min_match_score()

    results = []
    for candidate in candidates:
        match = compute_match(job, candidate)
        if match["score"] >= min_score:
            results.append(
                {
                    "candidate": candidate,
                    "score": match["score"],
                    "matched_terms": match["matched_terms"],
                }
            )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results

"""Métricas Prometheus mínimas para o fluxo de importação de candidatos na vaga."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

_MS_BUCKETS = (
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
    2500.0,
    5000.0,
    10000.0,
    30000.0,
    60000.0,
    120000.0,
    float("inf"),
)

_LLM_LABELS = ("llm_provider", "model_name")

vacancy_candidate_imports_total = Counter(
    "vacancy_candidate_imports_total",
    "Importações de candidatos na vaga iniciadas",
)

vacancy_candidate_import_failures_total = Counter(
    "vacancy_candidate_import_failures_total",
    "Falhas na importação de candidatos na vaga",
)

vacancy_candidate_import_duration_ms = Histogram(
    "vacancy_candidate_import_duration_ms",
    "Duração de importações concluídas com sucesso (ms)",
    buckets=_MS_BUCKETS,
)

vacancy_candidate_extractions_total = Counter(
    "vacancy_candidate_extractions_total",
    "Extrações LLM iniciadas (fluxo vaga)",
    labelnames=_LLM_LABELS,
)

vacancy_candidate_extraction_failures_total = Counter(
    "vacancy_candidate_extraction_failures_total",
    "Falhas na extração LLM (fluxo vaga)",
    labelnames=_LLM_LABELS,
)

vacancy_candidate_extraction_duration_ms = Histogram(
    "vacancy_candidate_extraction_duration_ms",
    "Duração de extrações LLM concluídas com sucesso (ms)",
    labelnames=_LLM_LABELS,
    buckets=_MS_BUCKETS,
)

vacancy_candidate_rankings_total = Counter(
    "vacancy_candidate_rankings_total",
    "Etapas de ranking (lote) iniciadas",
)

vacancy_candidate_ranking_failures_total = Counter(
    "vacancy_candidate_ranking_failures_total",
    "Falhas na etapa de ranking (sem persistência)",
)

vacancy_candidate_ranking_duration_ms = Histogram(
    "vacancy_candidate_ranking_duration_ms",
    "Duração da etapa de ranking por lote concluída com sucesso (ms)",
    buckets=_MS_BUCKETS,
)

vacancy_ranking_persist_total = Counter(
    "vacancy_ranking_persist_total",
    "Persistências de ranking concluídas com sucesso (por lote)",
)

vacancy_ranking_persist_failures_total = Counter(
    "vacancy_ranking_persist_failures_total",
    "Falhas ao persistir ranking",
)

vacancy_ranking_persist_duration_ms = Histogram(
    "vacancy_ranking_persist_duration_ms",
    "Duração da persistência de ranking concluída com sucesso (ms)",
    buckets=_MS_BUCKETS,
)

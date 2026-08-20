"""Preenche `resume_sha256` dos currículos já em disco (R-45).

Sem este backfill a dedup só valeria para currículos importados depois do deploy — e são
justamente os 449 já existentes que a recrutadora reimporta. Em produção (2026-08-20)
isso é 449 arquivos, ~80M; a leitura é em pedaços e leva segundos.

Arquivo que não abre fica com o campo vazio, e um campo vazio nunca casa com nada: o
currículo segue para o LLM como sempre. O erro caro seria o contrário — gravar hash
errado faria a importação **pular** um candidato que nunca foi importado.
"""

import hashlib
from pathlib import Path

from django.conf import settings
from django.db import migrations

_CHUNK = 64 * 1024


def _digest(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(_CHUNK):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def preencher(apps, schema_editor):
    Candidate = apps.get_model("core", "Candidate")
    raiz = Path(settings.MEDIA_ROOT)

    # `values_list` de propósito: num modelo histórico `candidate.resume_pdf` ainda é um
    # `FieldFile`, não a string do caminho — foi assim que a primeira versão desta
    # migration quebrou em produção, com `PosixPath / FieldFile`. Pedindo a coluna crua
    # vem `str`, e o caminho se monta sem depender do descritor do campo.
    pendentes = (
        Candidate.objects.filter(resume_sha256="")
        .exclude(resume_pdf="")
        .exclude(resume_pdf__isnull=True)
        .values_list("id", "resume_pdf")
    )

    atualizados = []
    for pk, nome in pendentes.iterator():
        digest = _digest(raiz / nome)
        if digest is None:
            continue
        atualizados.append(Candidate(id=pk, resume_sha256=digest))
        if len(atualizados) >= 200:
            Candidate.objects.bulk_update(atualizados, ["resume_sha256"])
            atualizados = []
    if atualizados:
        Candidate.objects.bulk_update(atualizados, ["resume_sha256"])


def limpar(apps, schema_editor):
    """Reversão: esvazia o campo. Nada se perde — ele é derivado do arquivo em disco."""
    Candidate = apps.get_model("core", "Candidate")
    Candidate.objects.exclude(resume_sha256="").update(resume_sha256="")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_candidate_resume_sha256"),
    ]

    operations = [
        migrations.RunPython(preencher, limpar),
    ]

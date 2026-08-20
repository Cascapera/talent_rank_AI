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

    pendentes = Candidate.objects.exclude(resume_pdf="").filter(resume_sha256="")
    atualizados = []
    for candidate in pendentes.only("id", "resume_pdf", "resume_sha256").iterator():
        digest = _digest(raiz / candidate.resume_pdf)
        if digest is None:
            continue
        candidate.resume_sha256 = digest
        atualizados.append(candidate)
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

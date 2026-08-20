"""Manipulacao de arquivo PDF e de upload (R-17).

O que e genuinamente sobre arquivo: gravar o curriculo, descobrir se ele existe em disco,
listar PDFs de uma pasta e desempacotar o que a recrutadora enviou (ZIPs e PDFs soltos).

Saiu de `pdf_extractor.py` — que apesar do nome era orquestracao de importacao — e de
`views.py`, que fazia zipfile e diretorio temporario dentro do handler HTTP.
"""

import hashlib
import zipfile
from pathlib import Path

from django.core.files import File

from .models import Candidate

_CHUNK = 64 * 1024


def _digest(path: Path) -> str | None:
    """SHA-256 do arquivo, lido em pedaços — currículo pode ter alguns MB."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(_CHUNK):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _same_file(a: Path, b: Path) -> bool:
    """Mesmo conteúdo? Tamanho primeiro (barato), hash só quando bate.

    Tamanho igual **não** é conteúdo igual: dois currículos podem ter o mesmo número de
    bytes. O `stat` é filtro, não veredito.
    """
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    digest_a = _digest(a)
    return digest_a is not None and digest_a == _digest(b)


def _atualizar_hash(candidate: Candidate, path: Path | None) -> None:
    """Mantém `resume_sha256` igual ao arquivo que está gravado (R-45).

    Escreve só quando muda, para não gerar UPDATE a cada reimportação de conteúdo
    idêntico — que é justamente o caso comum. Arquivo ilegível deixa o campo como está:
    hash errado é pior que hash ausente, porque faria a importação **pular** um currículo
    que nunca foi importado.
    """
    if path is None:
        return
    digest = _digest(path)
    if digest is None or candidate.resume_sha256 == digest:
        return
    candidate.resume_sha256 = digest
    candidate.save(update_fields=["resume_sha256"])


def _save_resume_pdf(candidate: Candidate, pdf_path: Path) -> None:
    """Salva ou substitui o PDF do currículo, sem deixar órfão em disco (R-31).

    O nome gravado tem uuid (`resume_upload_to`), então regravar nunca sobrescreve: cria
    arquivo novo e abandona o anterior, que fica no disco sem nenhuma referência no banco.
    Reimportar o mesmo candidato 10 vezes deixava 10 PDFs, 9 inalcançáveis.

    Duas defesas, nesta ordem:

    1. conteúdo idêntico ao que já está gravado — o caso comum, reimportar o mesmo lote —
       não grava nada e mantém o arquivo atual;
    2. conteúdo diferente: grava o novo **e só então** apaga o antigo. Nunca o contrário —
       se a gravação falhar no meio, o candidato fica com o currículo velho, não sem
       nenhum.

    Falha ao apagar o antigo não interrompe a importação: o pior caso é o órfão que já
    era o comportamento anterior.
    """
    origem = Path(pdf_path)
    anterior = _resume_path(candidate)
    nome_anterior = candidate.resume_pdf.name if candidate.resume_pdf else ""
    if anterior is not None and _same_file(anterior, origem):
        # Nada a gravar, mas o candidato pode ser anterior ao R-45 e estar sem hash.
        _atualizar_hash(candidate, anterior)
        return

    with open(origem, "rb") as f:
        candidate.resume_pdf.save(origem.name, File(f), save=True)
    _atualizar_hash(candidate, _resume_path(candidate))

    if anterior is None or anterior == _resume_path(candidate):
        return
    # O uuid do nome torna a colisão improvável, mas apagar currículo não se desfaz:
    # se qualquer outra linha ainda aponta para este arquivo, o órfão é o mal menor.
    if Candidate.objects.filter(resume_pdf=nome_anterior).exclude(pk=candidate.pk).exists():
        return
    try:
        anterior.unlink(missing_ok=True)
    except OSError:
        pass


def _resume_path(candidate: Candidate) -> Path | None:
    """Caminho do currículo em disco, ou `None` se não houver arquivo utilizável.

    O registro no banco não basta: o arquivo tem que existir. Um `media/` limpo sem
    limpar o banco não quebra o ranking — o candidato passa a ser avaliado pelos dados
    estruturados, em silêncio.
    """
    if not candidate.resume_pdf or not hasattr(candidate.resume_pdf, "path"):
        return None
    try:
        path = Path(candidate.resume_pdf.path)
    except (ValueError, OSError):
        return None
    return path if path.exists() else None


def _pdf_files_in(folder_path: str) -> list[Path]:
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Pasta nao encontrada: {folder}")
    return [folder] if folder.is_file() else sorted(folder.glob("*.pdf"))


def prepare_uploaded_files(uploaded_files: list, temp_dir: Path) -> None:
    """
    Processa arquivos enviados (ZIPs e PDFs) e coloca todos os PDFs em temp_dir.
    Suporta: multiplos ZIPs, multiplos PDFs, ou combinacao.
    """
    pdf_counter = 0
    for f in uploaded_files:
        dest = temp_dir / f.name
        with dest.open("wb") as out:
            for chunk in f.chunks():
                out.write(chunk)
        if zipfile.is_zipfile(dest):
            with zipfile.ZipFile(dest, "r") as zf:
                for member in zf.namelist():
                    if member.lower().endswith(".pdf") and not member.endswith("/"):
                        pdf_counter += 1
                        out_path = temp_dir / f"{pdf_counter:04d}.pdf"
                        with zf.open(member) as src, out_path.open("wb") as dst:
                            dst.write(src.read())
            dest.unlink(missing_ok=True)
        elif dest.suffix.lower() == ".pdf":
            pdf_counter += 1
            new_path = temp_dir / f"{pdf_counter:04d}.pdf"
            if dest != new_path:
                dest.rename(new_path)
        else:
            dest.unlink(missing_ok=True)

"""Manipulacao de arquivo PDF e de upload (R-17).

O que e genuinamente sobre arquivo: gravar o curriculo, descobrir se ele existe em disco,
listar PDFs de uma pasta e desempacotar o que a recrutadora enviou (ZIPs e PDFs soltos).

Saiu de `pdf_extractor.py` — que apesar do nome era orquestracao de importacao — e de
`views.py`, que fazia zipfile e diretorio temporario dentro do handler HTTP.
"""

import zipfile
from pathlib import Path

from django.core.files import File

from .models import Candidate


def _save_resume_pdf(candidate: Candidate, pdf_path: Path) -> None:
    """Salva ou substitui o PDF do currículo no candidato."""
    with open(pdf_path, "rb") as f:
        candidate.resume_pdf.save(Path(pdf_path).name, File(f), save=True)


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

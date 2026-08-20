"""Mede se o mesmo currículo entra no sistema com bytes diferentes.

Motivação (2026-08-20): a dedup por hash de PDF só funciona se o exportador do
LinkedIn Recruiter for determinístico. Se o mesmo perfil, exportado em momentos
diferentes, sai com `/CreationDate` diferente, os bytes mudam sem o conteúdo
mudar — e a dedup por bytes não pegaria justamente o caso mais comum.

Só lê arquivos. Não toca no banco, não escreve nada em `media/`.

Uso no servidor:
    cd /var/www/talent_rank_ai && source .venv/bin/activate
    python /tmp/medir_duplicatas.py

`pypdf` não é dependência do projeto (ver a nota no `requirements.txt`); está
instalado no servidor por herança do R-03. Este script é ferramenta de medição,
não caminho de produção — por isso vive em `scripts/` e não é importado por nada.
"""

import collections
import hashlib
import re
import sys
import time
from pathlib import Path

RAIZ = Path("media/resumes")
ESPACOS = re.compile(r"\s+")


def texto_normalizado(caminho: Path) -> str | None:
    """Texto do PDF com espaços colapsados, ou None se não deu para ler."""
    try:
        from pypdf import PdfReader

        paginas = PdfReader(str(caminho)).pages
        bruto = "".join((p.extract_text() or "") for p in paginas)
    except Exception:
        return None
    return ESPACOS.sub(" ", bruto).strip().lower()


def criado_em(caminho: Path) -> str:
    try:
        from pypdf import PdfReader

        meta = PdfReader(str(caminho)).metadata or {}
        return str(meta.get("/CreationDate", "")) or "(sem CreationDate)"
    except Exception:
        return "(erro)"


def main() -> int:
    if not RAIZ.is_dir():
        print(f"ERRO: {RAIZ} nao encontrado. Rode a partir de /var/www/talent_rank_ai")
        return 1

    arquivos = sorted(p for p in RAIZ.rglob("*") if p.is_file())
    print(f"{len(arquivos)} arquivos em {RAIZ}\n")

    por_bytes: dict[str, list[Path]] = collections.defaultdict(list)
    por_texto: dict[str, list[Path]] = collections.defaultdict(list)
    ilegiveis: list[Path] = []
    vazios: list[Path] = []

    inicio = time.time()
    for i, caminho in enumerate(arquivos, 1):
        if i % 100 == 0:
            print(f"  ... {i}/{len(arquivos)}", flush=True)

        por_bytes[hashlib.sha256(caminho.read_bytes()).hexdigest()].append(caminho)

        texto = texto_normalizado(caminho)
        if texto is None:
            ilegiveis.append(caminho)
            continue
        if not texto:
            vazios.append(caminho)
            continue
        por_texto[hashlib.sha256(texto.encode()).hexdigest()].append(caminho)

    print(f"\nleitura levou {time.time() - inicio:.0f}s\n")

    copias_bytes = sum(len(v) - 1 for v in por_bytes.values() if len(v) > 1)
    copias_texto = sum(len(v) - 1 for v in por_texto.values() if len(v) > 1)

    print(f"conteudos distintos por BYTES : {len(por_bytes)}")
    print(f"conteudos distintos por TEXTO : {len(por_texto)}")
    print(f"copias excedentes por BYTES   : {copias_bytes}")
    print(f"copias excedentes por TEXTO   : {copias_texto}")

    # O numero que decide: mesmo curriculo, bytes diferentes. Cada um destes e um
    # caso que a dedup por hash de bytes NAO pegaria e a dedup por texto pegaria.
    invisiveis = copias_texto - copias_bytes
    print(f"\n>>> mesmo texto com bytes diferentes: {invisiveis}")

    if ilegiveis:
        print(f"\n{len(ilegiveis)} arquivos ilegiveis pelo pypdf (ignorados na conta de texto)")
    if vazios:
        print(f"{len(vazios)} arquivos sem texto extraivel — provavel PDF de imagem")

    # Amostra: grupos com mesmo texto e mais de um hash de bytes, com o CreationDate
    # de cada um. E ai que se ve se o timestamp e a unica coisa que muda.
    print("\n--- amostra (mesmo texto, bytes diferentes) ---")
    mostrados = 0
    for caminhos in por_texto.values():
        if len(caminhos) < 2:
            continue
        hashes = {hashlib.sha256(c.read_bytes()).hexdigest() for c in caminhos}
        if len(hashes) < 2:
            continue
        print(f"\ngrupo de {len(caminhos)} arquivos, {len(hashes)} versoes de bytes:")
        for c in caminhos[:4]:
            print(f"  {c.relative_to(RAIZ)}  {c.stat().st_size:>8} bytes  {criado_em(c)}")
        mostrados += 1
        if mostrados == 5:
            break
    if mostrados == 0:
        print("nenhum — todo texto repetido veio de bytes identicos")

    return 0


if __name__ == "__main__":
    sys.exit(main())

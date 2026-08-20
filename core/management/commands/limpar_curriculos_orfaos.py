"""Etapa 2 do R-31: tira do ar os PDFs que nenhuma linha do banco referencia.

Órfão aqui é arquivo em `media/resumes/` que **nenhum** `Candidate.resume_pdf` aponta.
Eles vêm do comportamento anterior ao R-31: cada reimportação gravava um arquivo novo com
uuid novo e abandonava o anterior. Medido em produção em 2026-08-20: **270 de 719
arquivos, 33M — 41% do diretório**.

**O motivo de limpar não é disco.** São 33M num servidor que não está apertado. São
currículos de pessoas reais — nome, telefone, histórico — retidos sem vínculo com nenhum
candidato. O R-23 fechou o acesso de fora, então não estão expostos, mas retenção sem
finalidade é assunto de LGPD.

**Este comando não apaga.** Move para uma quarentena fora de `media/` e escreve um
manifesto que permite desfazer. Apagar currículo não se desfaz, e a decisão de apagar de
vez fica para depois de alguns dias com a aplicação em uso normal.

Uso:

    python manage.py limpar_curriculos_orfaos                 # só lista, não toca em nada
    python manage.py limpar_curriculos_orfaos --mover         # move para a quarentena
    python manage.py limpar_curriculos_orfaos --restaurar     # desfaz pelo manifesto
"""

import csv
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Candidate, ImportJob

MANIFESTO = "manifesto.csv"


def _quarentena() -> Path:
    """Fora de `media/`, para a próxima varredura não achar os mesmos arquivos de novo.

    No mesmo filesystem de propósito: o `mv` vira rename e não copia os 33M.
    """
    return Path(settings.MEDIA_ROOT).parent / "_quarentena_r31"


def _raiz() -> Path:
    return Path(settings.MEDIA_ROOT) / "resumes"


def importacao_viva() -> ImportJob | None:
    """Job `RUNNING` com heartbeat recente. Um job morto de ontem não conta.

    Enquanto uma importação roda, arquivos aparecem em disco antes de a linha existir no
    banco — e seriam vistos como órfãos.
    """
    limite = getattr(settings, "IMPORT_JOB_STALE_AFTER_SECONDS", 900)
    corte = timezone.now() - timedelta(seconds=limite)
    return ImportJob.objects.filter(
        status=ImportJob.Status.RUNNING, heartbeat_at__gte=corte
    ).first()


def encontrar_orfaos(dias: int) -> tuple[list[Path], list[Path]]:
    """Devolve `(orfaos, recentes_preservados)`.

    O corte por `mtime` é a segunda guarda, independente da checagem de job vivo: cobre a
    janela entre gravar o arquivo e gravar a linha, e o caso de uma importação que morreu
    no meio deixando arquivo sem dono que ainda pode ser reaproveitado.
    """
    raiz = _raiz()
    if not raiz.is_dir():
        return [], []

    referenciados = {
        Path(settings.MEDIA_ROOT) / nome
        for nome in Candidate.objects.exclude(resume_pdf="")
        .exclude(resume_pdf__isnull=True)
        .values_list("resume_pdf", flat=True)
    }

    corte = timezone.now() - timedelta(days=dias)
    orfaos, recentes = [], []
    for caminho in sorted(p for p in raiz.rglob("*") if p.is_file()):
        if caminho in referenciados:
            continue
        modificado = datetime.fromtimestamp(
            caminho.stat().st_mtime, tz=timezone.get_current_timezone()
        )
        (recentes if modificado > corte else orfaos).append(caminho)
    return orfaos, recentes


def mover_para_quarentena(orfaos: list[Path]) -> Path:
    """Move preservando a estrutura e registra o manifesto. Devolve o caminho dele."""
    destino_raiz = _quarentena()
    destino_raiz.mkdir(parents=True, exist_ok=True)
    manifesto = destino_raiz / MANIFESTO

    novo = not manifesto.exists()
    with open(manifesto, "a", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        if novo:
            escritor.writerow(["origem", "destino", "bytes", "movido_em"])
        for origem in orfaos:
            relativo = origem.relative_to(_raiz())
            destino = destino_raiz / relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            tamanho = origem.stat().st_size
            shutil.move(str(origem), str(destino))
            escritor.writerow([str(origem), str(destino), tamanho, timezone.now().isoformat()])
    return manifesto


def restaurar(manifesto: Path) -> tuple[int, list[str]]:
    """Devolve tudo do manifesto para o lugar de origem. `(restaurados, problemas)`."""
    restaurados, problemas = 0, []
    with open(manifesto, newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))

    sobraram = []
    for linha in linhas:
        origem, destino = Path(linha["origem"]), Path(linha["destino"])
        if not destino.exists():
            problemas.append(f"não está na quarentena: {destino}")
            continue
        if origem.exists():
            problemas.append(f"já existe no lugar de origem, não sobrescrevi: {origem}")
            sobraram.append(linha)
            continue
        origem.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destino), str(origem))
        restaurados += 1

    # Reescreve o manifesto só com o que não voltou, para não prometer restaurar duas vezes.
    with open(manifesto, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["origem", "destino", "bytes", "movido_em"])
        for linha in sobraram:
            escritor.writerow(
                [linha["origem"], linha["destino"], linha["bytes"], linha["movido_em"]]
            )
    return restaurados, problemas


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f}M"


class Command(BaseCommand):
    help = "Move para quarentena os PDFs de currículo que nenhuma linha do banco referencia (R-31, etapa 2)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mover",
            action="store_true",
            help="Move de verdade. Sem esta flag o comando só lista.",
        )
        parser.add_argument(
            "--restaurar",
            action="store_true",
            help="Devolve para media/ tudo o que está no manifesto da quarentena.",
        )
        parser.add_argument(
            "--dias",
            type=int,
            default=1,
            help="Preserva arquivos modificados nos últimos N dias (padrão: 1).",
        )

    def handle(self, *args, **options):
        if options["restaurar"]:
            return self._restaurar()

        job = importacao_viva()
        if job is not None:
            raise CommandError(
                f"importação {job.id} está rodando (heartbeat em {job.heartbeat_at}). "
                "Arquivo gravado agora ainda não tem linha no banco e pareceria órfão. "
                "Rode de novo quando ela terminar."
            )

        orfaos, recentes = encontrar_orfaos(options["dias"])
        total = sum(p.stat().st_size for p in orfaos)

        if recentes:
            self.stdout.write(
                f"{len(recentes)} arquivo(s) sem dono preservados por terem menos de "
                f"{options['dias']} dia(s)."
            )

        if not orfaos:
            self.stdout.write(self.style.SUCCESS("Nenhum órfão para limpar."))
            return

        self.stdout.write(f"\n{len(orfaos)} órfão(s), {_mb(total)}:\n")
        for caminho in orfaos[:20]:
            self.stdout.write(f"  {caminho.relative_to(_raiz())}  {_mb(caminho.stat().st_size)}")
        if len(orfaos) > 20:
            self.stdout.write(f"  ... e mais {len(orfaos) - 20}")

        if not options["mover"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nNada foi movido. Rode com --mover para enviar à quarentena.\n"
                    "Nenhum arquivo é apagado: eles vão para uma pasta fora de media/ e "
                    "podem voltar com --restaurar."
                )
            )
            return

        manifesto = mover_para_quarentena(orfaos)
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{len(orfaos)} arquivo(s) movidos para {_quarentena()} ({_mb(total)} "
                f"liberados de media/).\nManifesto em {manifesto} — desfaça com --restaurar."
            )
        )

    def _restaurar(self):
        manifesto = _quarentena() / MANIFESTO
        if not manifesto.is_file():
            raise CommandError(f"não achei o manifesto em {manifesto}")

        restaurados, problemas = restaurar(manifesto)
        for problema in problemas:
            self.stdout.write(self.style.WARNING(f"  {problema}"))
        self.stdout.write(self.style.SUCCESS(f"{restaurados} arquivo(s) devolvidos a media/."))

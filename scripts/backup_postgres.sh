#!/usr/bin/env bash
set -euo pipefail

# Backup semanal do PostgreSQL.
# Requer as variaveis de ambiente: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD.
# Pode carregar um arquivo .env via ENV_FILE.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ENV_FILE="$SCRIPT_DIR/../.env"

if [[ -n "${ENV_FILE:-}" && -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
elif [[ -f "$DEFAULT_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$DEFAULT_ENV_FILE"
  set +a
fi

BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/../backups}"
BACKUP_FILE="${BACKUP_FILE:-$BACKUP_DIR/db_backup.dump}"
BACKUP_PREV_FILE="${BACKUP_PREV_FILE:-$BACKUP_DIR/db_backup.prev.dump}"

mkdir -p "$BACKUP_DIR"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "Dry-run: backup atual -> $BACKUP_FILE"
  echo "Dry-run: backup anterior -> $BACKUP_PREV_FILE"
  exit 0
fi

export PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD nao definida}"

if [[ -f "$BACKUP_FILE" ]]; then
  mv -f "$BACKUP_FILE" "$BACKUP_PREV_FILE"
fi

pg_dump \
  --host="${POSTGRES_HOST:?POSTGRES_HOST nao definida}" \
  --port="${POSTGRES_PORT:?POSTGRES_PORT nao definida}" \
  --username="${POSTGRES_USER:?POSTGRES_USER nao definida}" \
  --format=custom \
  --file="$BACKUP_FILE" \
  "${POSTGRES_DB:?POSTGRES_DB nao definida}"

echo "Backup concluido: $BACKUP_FILE (anterior: $BACKUP_PREV_FILE)"

#!/bin/sh
# Respaldo de la base de datos. Uso en el VPS: ./deploy/backup.sh  (programable con cron)
set -e
cd "$(dirname "$0")/.."
. ./.env
mkdir -p backups
archivo="backups/novera-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$archivo"
# Conserva los últimos 30 respaldos
ls -1t backups/novera-*.sql.gz | tail -n +31 | xargs -r rm --
echo "Respaldo creado: $archivo"

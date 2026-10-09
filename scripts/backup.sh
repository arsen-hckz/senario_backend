#!/usr/bin/env bash
# Daily backup of the Postgres database and uploaded media, run from cron on
# the droplet:
#   15 3 * * * /var/www/senario_backend/scripts/backup.sh >> /var/log/senario-backup.log 2>&1
#
# Restore the database:
#   gunzip -c db-YYYY-MM-DD.sql.gz | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
#
# These copies live on the droplet itself, so they cover mistakes and bad
# migrations, not losing the droplet. DigitalOcean droplet backups cover that.
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/var/backups/senario}
KEEP_DAYS=14

cd "$(dirname "$0")/.."
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp=$(date +%F)

# Write to a temp name first so a failed dump never replaces a good one.
$DC exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$BACKUP_DIR/db-$stamp.sql.gz.tmp"
mv "$BACKUP_DIR/db-$stamp.sql.gz.tmp" "$BACKUP_DIR/db-$stamp.sql.gz"

$DC exec -T web tar czf - -C /app media > "$BACKUP_DIR/media-$stamp.tar.gz.tmp"
mv "$BACKUP_DIR/media-$stamp.tar.gz.tmp" "$BACKUP_DIR/media-$stamp.tar.gz"

find "$BACKUP_DIR" -name '*.gz' -mtime +$KEEP_DAYS -delete
echo "$(date -Is) backup ok: $(du -sh "$BACKUP_DIR" | cut -f1) in $BACKUP_DIR"

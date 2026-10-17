#!/usr/bin/env sh
# Run from the directory containing compose.yaml. BACKUP_DIR must be outside the app checkout.
set -eu

: "${BACKUP_DIR:?Set BACKUP_DIR to an existing backup directory}"
BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
case "$BACKUP_RETENTION_DAYS" in *[!0-9]*|'') echo "BACKUP_RETENTION_DAYS must be a positive integer" >&2; exit 2;; esac
mkdir -p "$BACKUP_DIR"
umask 077

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_DIR/hpoint-$timestamp.dump"
temporary="$target.partial"

trap 'rm -f "$temporary"' EXIT HUP INT TERM
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$temporary"
test -s "$temporary"
mv "$temporary" "$target"
sha256sum "$target" > "$target.sha256"
find "$BACKUP_DIR" -type f \( -name 'hpoint-*.dump' -o -name 'hpoint-*.dump.sha256' \) -mtime +"$BACKUP_RETENTION_DAYS" -delete
trap - EXIT HUP INT TERM
printf 'Created %s\n' "$target"

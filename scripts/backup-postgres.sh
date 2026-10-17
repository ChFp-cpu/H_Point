#!/usr/bin/env sh
# Run from the directory containing compose.yaml. BACKUP_DIR must be outside the app checkout.
set -eu

: "${BACKUP_DIR:?Set BACKUP_DIR to an existing backup directory}"
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
trap - EXIT HUP INT TERM
printf 'Created %s\n' "$target"

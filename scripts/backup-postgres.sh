#!/usr/bin/env sh
# Run from the directory containing compose.yaml. BACKUP_DIR must be outside the app checkout.
set -eu

: "${BACKUP_DIR:?Set BACKUP_DIR to an existing backup directory}"
BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
case "$BACKUP_RETENTION_DAYS" in *[!0-9]*|''|0) echo "BACKUP_RETENTION_DAYS must be a positive integer" >&2; exit 2;; esac
umask 077
command -v flock >/dev/null 2>&1 || { echo 'flock is required' >&2; exit 2; }
# Resolve before creating/deleting files. The backup directory must never be
# the application checkout, its parent, or a child of the checkout.
BACKUP_DIR=$(python3 - "$BACKUP_DIR" "$BACKUP_RETENTION_DAYS" <<'PY'
import pathlib,sys
root=pathlib.Path.cwd().resolve();target=pathlib.Path(sys.argv[1]).expanduser().resolve()
if int(sys.argv[2])<1:raise SystemExit('BACKUP_RETENTION_DAYS must be positive')
if target==root or target in root.parents or root in target.parents:
    raise SystemExit('BACKUP_DIR must be outside the application checkout')
print(target)
PY
)
test -f compose.yaml || { echo 'Run from the application checkout' >&2; exit 2; }
mkdir -p "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || { echo 'Another backup is already running' >&2; exit 75; }

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_DIR/hpoint-$timestamp-$$.dump"
temporary="$target.partial"

trap 'rm -f "$temporary"' EXIT HUP INT TERM
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$temporary"
test -s "$temporary"
# Validate the PostgreSQL archive catalogue before making it a retained backup.
docker compose exec -T db pg_restore --list < "$temporary" > /dev/null
mv "$temporary" "$target"
sha256sum "$target" > "$target.sha256"
# Only this script's direct outputs belong to its retention policy. Preserve
# independently managed release/drill archives in any nested directories.
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'hpoint-*.dump' -o -name 'hpoint-*.dump.sha256' \) -mtime +"$BACKUP_RETENTION_DAYS" -delete
trap - EXIT HUP INT TERM
printf 'Created %s\n' "$target"

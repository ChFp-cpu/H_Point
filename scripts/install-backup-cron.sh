#!/usr/bin/env sh
# Install one idempotent hourly backup job for this deployment user.
set -eu
umask 077
root=$(pwd -P)
test "$root" = /opt/hpoint/H_Point || { echo 'Expected /opt/hpoint/H_Point' >&2; exit 2; }
test -f compose.yaml && test -f scripts/backup-postgres.sh
command -v crontab >/dev/null 2>&1
command -v flock >/dev/null 2>&1
backup=/opt/hpoint/backups/automatic
mkdir -p "$backup"
chmod 700 "$backup"
temporary=$(mktemp)
existing=$(mktemp)
listing_error=$(mktemp)
trap 'rm -f "$temporary" "$existing" "$listing_error"' EXIT HUP INT TERM
# Preserve all unrelated jobs; this exact marker owns only our single line.
# A read/permission/system failure must never be mistaken for an empty table.
if LC_ALL=C crontab -l > "$existing" 2> "$listing_error"; then
    :
elif test ! -s "$existing" && grep -Eq '^no crontab for [^[:space:]]+$' "$listing_error"; then
    :
else
    cat "$listing_error" >&2
    echo 'Cannot read existing crontab; no jobs were changed' >&2
    exit 2
fi
sed '/# hpoint-managed-backup$/d' "$existing" > "$temporary"
printf '%s\n' '15 * * * * PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; export PATH; cd /opt/hpoint/H_Point && BACKUP_DIR=/opt/hpoint/backups/automatic sh scripts/backup-postgres.sh >> /opt/hpoint/backups/automatic/backup.log 2>&1 # hpoint-managed-backup' >> "$temporary"
crontab "$temporary"
printf 'Installed hourly backup job at minute 15; retention defaults to 14 days.\n'

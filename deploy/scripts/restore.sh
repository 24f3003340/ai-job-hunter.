#!/usr/bin/env bash
# Restore a backup made by backup.sh into an EMPTY database and an EMPTY storage directory.
#   BACKUP=/backups/jobhunter-<ts> TARGET_STORAGE_DIR=/restore/storage PGDATABASE=<empty db> [BACKUP_PASSPHRASE=...] deploy/scripts/restore.sh
# Refuses to touch a non-empty target (restoring over a live database is a manual, deliberate decision).
set -euo pipefail
: "${BACKUP:?}" "${TARGET_STORAGE_DIR:?}" "${PGDATABASE:?}"
PG_RESTORE_CMD=${PG_RESTORE_CMD:-pg_restore}
PSQL_CMD=${PSQL_CMD:-psql}

( cd "$BACKUP" && sha256sum --quiet -c manifest.sha256 ) || { echo "backup failed its checksum manifest" >&2; exit 1; }

tables=$($PSQL_CMD --dbname="$PGDATABASE" -Atc "select count(*) from information_schema.tables where table_schema='public'")
[ "$tables" = "0" ] || { echo "target database $PGDATABASE is not empty ($tables tables)" >&2; exit 1; }
if [ -d "$TARGET_STORAGE_DIR" ] && [ -n "$(ls -A "$TARGET_STORAGE_DIR")" ]; then echo "target storage dir is not empty" >&2; exit 1; fi
mkdir -p "$TARGET_STORAGE_DIR"; chmod 700 "$TARGET_STORAGE_DIR"

dump="$BACKUP/db.dump"; tgz="$BACKUP/storage.tgz"
if [ -f "$BACKUP/db.dump.enc" ]; then
  : "${BACKUP_PASSPHRASE:?backup is encrypted; set BACKUP_PASSPHRASE}"
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$BACKUP/db.dump.enc" -out "$tmp/db.dump"
  openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$BACKUP/storage.tgz.enc" -out "$tmp/storage.tgz"
  dump="$tmp/db.dump"; tgz="$tmp/storage.tgz"
fi
$PG_RESTORE_CMD --no-owner --exit-on-error --dbname="$PGDATABASE" < "$dump"
tar -C "$TARGET_STORAGE_DIR" -xzf "$tgz"
echo "restored into $PGDATABASE and $TARGET_STORAGE_DIR"

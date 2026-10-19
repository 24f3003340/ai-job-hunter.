#!/usr/bin/env bash
# Prove a backup is restorable: restore into a scratch database + scratch directory, then check
#   1) the manifest checksums, 2) Alembic revision, 3) every table's row count equals the count recorded at backup time,
#   4) every stored file matches its database record (size + SHA-256, no orphans).
# Needs a role that may CREATE/DROP DATABASE and the backend virtualenv for step 4 (VERIFY_PYTHON, default python).
#   BACKUP=/backups/jobhunter-<ts> PGHOST=.. PGPORT=.. PGUSER=.. PGPASSWORD=.. [BACKUP_PASSPHRASE=..] deploy/scripts/verify_restore.sh
set -euo pipefail
: "${BACKUP:?}"
PSQL_ADMIN=${PSQL_ADMIN:-psql}
VERIFY_PYTHON=${VERIFY_PYTHON:-python}
here=$(cd "$(dirname "$0")" && pwd)
backend="$here/../../backend"
scratch="jh_restore_check_$(date +%s)"
dir=$(mktemp -d)
cleanup() { $PSQL_ADMIN -d postgres -qc "drop database if exists \"$scratch\" with (force)" >/dev/null 2>&1 || true; rm -rf "$dir"; }
trap cleanup EXIT

$PSQL_ADMIN -d postgres -qc "create database \"$scratch\""
PGDATABASE="$scratch" TARGET_STORAGE_DIR="$dir/storage" BACKUP="$BACKUP" "$here/restore.sh"

fail=0
want=$(cat "$BACKUP/alembic_version.txt")
got=$($PSQL_ADMIN -d "$scratch" -Atc "select version_num from alembic_version")
[ "$want" = "$got" ] && echo "ok   alembic revision $got" || { echo "FAIL alembic revision: backup=$want restored=$got"; fail=1; }

while read -r table expected; do
  actual=$($PSQL_ADMIN -d "$scratch" -Atc "select count(*) from $table")
  if [ "$expected" = "$actual" ]; then echo "ok   $table = $actual"; else echo "FAIL $table: expected $expected, restored $actual"; fail=1; fi
done < "$BACKUP/rowcounts.txt"

url="postgresql+psycopg://${PGUSER:-postgres}:${PGPASSWORD:-}@${PGHOST:-127.0.0.1}:${PGPORT:-5432}/$scratch"
( cd "$backend" && "$VERIFY_PYTHON" scripts/verify_storage.py --storage-dir "$dir/storage" --database-url "$url" ) || fail=1

[ "$fail" = 0 ] && echo "RESTORE VERIFIED" || { echo "RESTORE VERIFICATION FAILED"; exit 1; }

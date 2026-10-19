#!/usr/bin/env bash
# Consistent backup of the database (pg_dump -Fc) and the private upload store, with a checksummed manifest.
#
# Native:   PGHOST=... PGPORT=... PGUSER=... PGPASSWORD=... PGDATABASE=... STORAGE_DIR=/var/lib/jobhunter/storage \
#           BACKUP_DIR=/backups deploy/scripts/backup.sh
# Compose:  PG_DUMP_CMD="docker compose -f deploy/docker-compose.staging.yml --env-file deploy/.env.staging exec -T postgres pg_dump -U jobhunter" \
#           PSQL_CMD="... exec -T postgres psql -U jobhunter" STORAGE_DIR=<path of the uploads volume on the host> ...
# Optional encryption at rest: set BACKUP_PASSPHRASE (AES-256, PBKDF2). Keep the passphrase OUTSIDE the backup location.
set -euo pipefail
: "${PGDATABASE:?}" "${STORAGE_DIR:?}" "${BACKUP_DIR:?}"
PG_DUMP_CMD=${PG_DUMP_CMD:-pg_dump}
PSQL_CMD=${PSQL_CMD:-psql}
ts=$(date -u +%Y%m%dT%H%M%SZ)
out="$BACKUP_DIR/jobhunter-$ts"
umask 077
mkdir -p "$out"

$PG_DUMP_CMD --format=custom --no-owner --dbname="$PGDATABASE" > "$out/db.dump"
tar -C "$STORAGE_DIR" -czf "$out/storage.tgz" .

# Row counts let the restore check prove the dump is complete, not merely loadable.
for t in users candidate_profiles documents cv_parses jobs resume_versions claim_reviews applications application_answers application_approvals application_events audit_events; do
  n=$($PSQL_CMD --dbname="$PGDATABASE" -Atc "select count(*) from $t")
  echo "$t $n"
done > "$out/rowcounts.txt"
$PSQL_CMD --dbname="$PGDATABASE" -Atc "select version_num from alembic_version" > "$out/alembic_version.txt"

if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
  for f in db.dump storage.tgz; do
    openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -in "$out/$f" -out "$out/$f.enc"
    rm "$out/$f"
  done
  echo "encrypted: yes" > "$out/encryption.txt"
else
  echo "encrypted: NO (set BACKUP_PASSPHRASE or encrypt the destination volume)" > "$out/encryption.txt"
fi
( cd "$out" && sha256sum $(ls | grep -v '^manifest.sha256$') > manifest.sha256 )
echo "$out"

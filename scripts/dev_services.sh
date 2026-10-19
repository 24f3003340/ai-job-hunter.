#!/usr/bin/env bash
# Start throwaway PostgreSQL 16 + Redis 7 as plain processes (no Docker needed). Linux, run as root or a user that
# can `su postgres`. Prints the env vars the integration tests expect.  Usage: scripts/dev_services.sh start|stop
set -euo pipefail
PGBIN=${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)}
PGDATA=${PGDATA:-/tmp/jh_pgdata}; PGPORT=${PGPORT:-5433}; REDISPORT=${REDISPORT:-6380}
case "${1:-}" in
  start)
    if [ ! -d "$PGDATA" ]; then
      mkdir -p "$PGDATA"; chown postgres "$PGDATA"
      su postgres -c "$PGBIN/initdb -D $PGDATA -A scram-sha-256 -U jobhunter --pwfile=<(echo devpassword) >/dev/null"
    fi
    su postgres -c "$PGBIN/pg_ctl -D $PGDATA -o '-p $PGPORT -k /tmp' -l /tmp/jh_pg.log -w start" || true
    PGPASSWORD=devpassword psql -h 127.0.0.1 -p "$PGPORT" -U jobhunter -d postgres -tc \
      "select 1 from pg_database where datname='jobhunter_test'" | grep -q 1 || \
      PGPASSWORD=devpassword psql -h 127.0.0.1 -p "$PGPORT" -U jobhunter -d postgres -c "create database jobhunter_test"
    redis-server --port "$REDISPORT" --save "" --daemonize yes >/dev/null
    echo "export JOBHUNTER_TEST_DATABASE_URL=postgresql+psycopg://jobhunter:devpassword@127.0.0.1:$PGPORT/jobhunter_test"
    echo "export JOBHUNTER_TEST_REDIS_URL=redis://127.0.0.1:$REDISPORT/0" ;;
  stop)
    su postgres -c "$PGBIN/pg_ctl -D $PGDATA -m fast stop" || true
    redis-cli -p "$REDISPORT" shutdown nosave || true ;;
  *) echo "usage: $0 start|stop"; exit 2 ;;
esac

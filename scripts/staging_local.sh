#!/usr/bin/env bash
# Staging-LIKE stack without Docker, for verification in sandboxes/CI-less machines:
#   PostgreSQL 16 + password-protected Redis + FastAPI (production config, 2 workers) + TLS gateway (Caddy stand-in)
#   + STARTTLS/AUTH SMTP sink.  Everything under ./.staging (git-ignored).   Usage: scripts/staging_local.sh start|stop
# NOT the real deployment: that is deploy/docker-compose.staging.yml (see docs/DEPLOYMENT.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
S="$ROOT/.staging"; PY="${STAGING_PYTHON:-$ROOT/backend/.venv/bin/python}"
PGBIN=${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)}
PGPORT=${PGPORT:-5434}; REDISPORT=${REDISPORT:-6381}; API_PORT=${API_PORT:-8021}; HTTPS_PORT=${HTTPS_PORT:-8443}; SMTP_PORT=${SMTP_PORT:-2525}
PGPASS=stagingpw; REDISPASS=stagingredis; SMTPPASS=sinkpw
case "${1:-}" in
stop)
  for f in gateway api smtp redis; do [ -f "$S/$f.pid" ] && kill "$(cat "$S/$f.pid")" 2>/dev/null || true; done
  [ -d "$S/pgdata" ] && { su postgres -c "$PGBIN/pg_ctl -D $S/pgdata -m fast stop" >/dev/null 2>&1 || true; }
  echo stopped ;;
start)
  "$0" stop >/dev/null 2>&1 || true
  rm -rf "$S" && mkdir -p "$S/storage" "$S/mail" && chmod 777 "$S"
  # 1. TLS certificate valid for localhost / 127.0.0.1 (used by the gateway AND trusted by the backend for SMTP)
  openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=localhost" -keyout "$S/key.pem" -out "$S/cert.pem" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
  # 2. PostgreSQL
  mkdir "$S/pgdata" && chown postgres "$S/pgdata"
  su postgres -c "$PGBIN/initdb -D $S/pgdata -A scram-sha-256 -U jobhunter --pwfile=<(echo $PGPASS) >/dev/null"
  su postgres -c "$PGBIN/pg_ctl -D $S/pgdata -o '-p $PGPORT -k $S' -l $S/pg.log -w start" >/dev/null 2>&1
  PGPASSWORD=$PGPASS psql -h 127.0.0.1 -p "$PGPORT" -U jobhunter -d postgres -qc "create database jobhunter"
  # 3. Redis with a password
  redis-server --port "$REDISPORT" --requirepass "$REDISPASS" --save "" --appendonly no --daemonize yes --pidfile "$S/redis.pid" --logfile "$S/redis.log" >/dev/null 2>&1
  # 4. SMTP sink (STARTTLS + AUTH)
  setsid nohup "$PY" "$ROOT/scripts/smtp_sink.py" --port "$SMTP_PORT" --cert "$S/cert.pem" --key "$S/key.pem" --user mailer --password "$SMTPPASS" --dir "$S/mail" >"$S/smtp.log" 2>&1 </dev/null &
  echo $! > "$S/smtp.pid"
  # 5. frontend build (same-origin API) and backend (production config)
  (cd "$ROOT/frontend" && VITE_API_URL=/api/v1 npm run build >/dev/null)
  export JOBHUNTER_ENV=production
  export JOBHUNTER_DATABASE_URL="postgresql+psycopg://jobhunter:$PGPASS@127.0.0.1:$PGPORT/jobhunter"
  export JOBHUNTER_PUBLIC_BASE_URL="https://localhost:$HTTPS_PORT"
  export JOBHUNTER_CORS_ORIGINS="[\"https://localhost:$HTTPS_PORT\"]"
  export JOBHUNTER_TRUST_PROXY_HEADERS=true JOBHUNTER_REQUIRE_VERIFIED_EMAIL=true
  export JOBHUNTER_RATE_LIMIT_BACKEND=redis JOBHUNTER_REDIS_URL="redis://:$REDISPASS@127.0.0.1:$REDISPORT/0"
  export JOBHUNTER_EMAIL_BACKEND=smtp JOBHUNTER_EMAIL_FROM=no-reply@staging.invalid JOBHUNTER_SMTP_HOST=127.0.0.1
  export JOBHUNTER_SMTP_PORT="$SMTP_PORT" JOBHUNTER_SMTP_USER=mailer JOBHUNTER_SMTP_PASSWORD="$SMTPPASS" JOBHUNTER_SMTP_SECURITY=starttls JOBHUNTER_SMTP_CA_FILE="$S/cert.pem"
  export JOBHUNTER_ALLOW_UNSCANNED_UPLOADS=true   # no ClamAV in this environment: an explicit, recorded override
  export JOBHUNTER_STORAGE_DIR="$S/storage" JOBHUNTER_AI_PROVIDER=rule_based
  # TEST-ONLY: the E2E suite makes many auth calls from one IP. Real staging keeps the defaults.
  export JOBHUNTER_RATE_LIMIT_AUTH=${E2E_RATE_AUTH:-100000/minute} JOBHUNTER_RATE_LIMIT_DEFAULT=100000/minute JOBHUNTER_RATE_LIMIT_UPLOAD=100000/hour JOBHUNTER_RATE_LIMIT_GENERATE=100000/hour
  (cd "$ROOT/backend" && "$PY" -m alembic upgrade head)
  (cd "$ROOT/backend" && setsid nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header >"$S/api.log" 2>&1 </dev/null & echo $! > "$S/api.pid")
  # 6. gateway
  (cd "$ROOT" && UPSTREAM="http://127.0.0.1:$API_PORT" DIST="$ROOT/frontend/dist" setsid nohup "$PY" -m uvicorn --app-dir scripts staging_gateway:app --host 127.0.0.1 --port "$HTTPS_PORT" \
     --ssl-keyfile "$S/key.pem" --ssl-certfile "$S/cert.pem" --log-level warning >"$S/gateway.log" 2>&1 </dev/null & echo $! > "$S/gateway.pid")
  for i in $(seq 1 60); do curl -sk "https://localhost:$HTTPS_PORT/health" | grep -q ok && break; sleep 0.5; done
  curl -sk "https://localhost:$HTTPS_PORT/health" | grep -q ok || { echo "stack did not come up; see $S/*.log" >&2; exit 1; }
  echo "staging-like stack up: https://localhost:$HTTPS_PORT   (mail dir: $S/mail)"
  echo "export E2E_EXTERNAL=1 E2E_BASE_URL=https://localhost:$HTTPS_PORT E2E_MAIL_DIR=$S/mail" ;;
*) echo "usage: $0 start|stop"; exit 2 ;;
esac

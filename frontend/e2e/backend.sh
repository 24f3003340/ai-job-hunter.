#!/usr/bin/env bash
# Starts a REAL backend for the end-to-end tests on a throwaway SQLite database. Nothing external is contacted:
# e-mail goes to .eml files, the AI provider is the local rule-based one, no malware scanner is configured.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
E2E="$ROOT/frontend/.e2e"
rm -rf "$E2E/data" && mkdir -p "$E2E/data"
export JOBHUNTER_ENV=development
export JOBHUNTER_DATABASE_URL="sqlite:///$E2E/data/e2e.db"
export JOBHUNTER_STORAGE_DIR="$E2E/data/storage"
export JOBHUNTER_EMAIL_BACKEND=file
export JOBHUNTER_MAIL_DIR="$E2E/data/mail"
export JOBHUNTER_RATE_LIMIT_AUTH=1000/minute
export JOBHUNTER_RATE_LIMIT_DEFAULT=100000/minute
export JOBHUNTER_RATE_LIMIT_UPLOAD=1000/hour
export JOBHUNTER_RATE_LIMIT_GENERATE=1000/hour
export JOBHUNTER_AI_PROVIDER=rule_based
cd "$ROOT/backend"
PY="${E2E_PYTHON:-.venv/bin/python}"
"$PY" -m alembic upgrade head
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "${E2E_BACKEND_PORT:-8011}" --log-level warning

#!/bin/sh
# Seed a few demo jobs. Watch them run in /admin/catalog/job/
set -e
BASE=${BASE:-http://localhost:8000}
TOKEN=${JOBS_API_TOKEN:-demo-token}
STAMP=$(date +%s)

post() {
  curl -sS -X POST "$BASE/api/jobs/" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$1"
  echo
}

post "{\"job_type\":\"git_pull\",\"payload\":{\"repo\":\"book-1342.git\",\"ref\":\"main\",\"after\":\"abc123\"},\"idempotency_key\":\"demo-git-$STAMP\"}"
post "{\"job_type\":\"workflow_ingest\",\"payload\":{\"id\":99999},\"idempotency_key\":\"demo-workflow-$STAMP\"}"
post "{\"job_type\":\"rebuild\",\"payload\":{\"kind\":\"errata\",\"id\":1342},\"idempotency_key\":\"demo-rebuild-$STAMP\"}"

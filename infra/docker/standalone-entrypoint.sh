#!/bin/bash
# Runs the LogAn API and the built web workbench together in one container.
# If either process exits, the container exits with that status so
# orchestrators can restart it.
set -euo pipefail

uvicorn app.main:app \
    --app-dir apps/api \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${LOGAN_API_WORKERS:-1}" \
    --log-level "${LOGAN_LOG_LEVEL:-info}" &
api_pid=$!

npm run start --workspace @logan/web -- --hostname 0.0.0.0 --port 3000 &
web_pid=$!

stop_children() {
    kill -TERM "$api_pid" "$web_pid" 2>/dev/null || true
}
trap stop_children TERM INT

set +e
wait -n "$api_pid" "$web_pid"
status=$?
set -e
stop_children
exit "$status"

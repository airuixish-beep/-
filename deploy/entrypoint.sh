#!/usr/bin/env sh
set -eu

mkdir -p /app/media /app/staticfiles

if [ "${OPENCLAW_ENABLED:-False}" = "True" ] || [ "${OPENCLAW_ENABLED:-false}" = "true" ]; then
  if ! command -v "${OPENCLAW_COMMAND:-openclaw}" >/dev/null 2>&1; then
    echo "OpenClaw command not found: ${OPENCLAW_COMMAND:-openclaw}" >&2
    exit 1
  fi
fi

if [ "${DB_ENGINE:-sqlite}" = "mysql" ]; then
  python - <<'PY'
import os
import socket
import time

host = os.environ.get("DB_HOST", "db")
port = int(os.environ.get("DB_PORT", "3306"))

for _ in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit("MySQL is not reachable")
PY
fi

if [ "${DEBUG:-False}" = "False" ] || [ "${DEBUG:-false}" = "false" ]; then
  python manage.py check --deploy --fail-level WARNING
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec daphne -b 0.0.0.0 -p 8000 config.asgi:application

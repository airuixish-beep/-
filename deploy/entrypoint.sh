#!/usr/bin/env sh
set -eu

mkdir -p /app/media /app/staticfiles

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

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120

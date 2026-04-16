#!/usr/bin/env sh
set -eu

DB_PATH="/app/data/db.sqlite3"
mkdir -p /app/data /app/media /app/staticfiles

if [ ! -f "$DB_PATH" ]; then
  touch "$DB_PATH"
fi

export SQLITE_PATH="$DB_PATH"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120

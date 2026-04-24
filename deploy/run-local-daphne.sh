#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"

if [ ! -d ".venv" ]; then
  echo "未找到 .venv，请先创建并安装依赖。"
  exit 1
fi

if [ -f ".env.local" ]; then
  set -a
  . ".env.local"
  set +a
elif [ -f ".env" ]; then
  set -a
  . ".env"
  set +a
fi

export DEPLOY_ENV="${DEPLOY_ENV:-local}"
export DEBUG="${DEBUG:-True}"
export DB_ENGINE="${DB_ENGINE:-mysql}"
export DB_NAME="${DB_NAME:-xuanor_local}"
export DB_USER="${DB_USER:-xuanor}"
export DB_PASSWORD="${DB_PASSWORD:-xuanor}"
export DB_HOST="${DB_HOST:-127.0.0.1}"
export DB_PORT="${DB_PORT:-3306}"
export CHAT_REALTIME_ENABLED="${CHAT_REALTIME_ENABLED:-False}"
export CHANNEL_LAYER_BACKEND="${CHANNEL_LAYER_BACKEND:-memory}"
export SITE_URL="${SITE_URL:-http://127.0.0.1:8000}"

source .venv/bin/activate

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
python manage.py seed_product_demo

exec daphne -b 127.0.0.1 -p 8000 config.asgi:application

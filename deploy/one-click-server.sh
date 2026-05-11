#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"

MODE="${1:-deploy}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.server}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1"
    exit 1
  }
}

is_interactive() {
  [ -t 0 ]
}

normalize_host() {
  python3 - "$1" <<'PY'
from urllib.parse import urlparse
import sys
value = sys.argv[1].strip()
if not value:
    raise SystemExit(0)
parsed = urlparse(value if '://' in value else f'//{value}')
host = parsed.hostname or value.split('/')[0]
print(host)
PY
}

normalize_port() {
  local value="$1"
  python3 - "$value" <<'PY'
import sys
value = sys.argv[1].strip()
if not value:
    raise SystemExit(0)
port = int(value)
if not (1 <= port <= 65535):
    raise SystemExit(1)
print(port)
PY
}

build_origin() {
  local host="$1"
  local port="$2"
  if [ "$port" = "80" ]; then
    printf 'http://%s' "$host"
  else
    printf 'http://%s:%s' "$host" "$port"
  fi
}

generate_secret_key() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
}

get_env_value() {
  python3 - "$ENV_FILE" "$1" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
for line in path.read_text().splitlines():
    if line.startswith(f"{key}="):
        print(line.split("=", 1)[1])
        break
PY
}

set_env_value() {
  python3 - "$ENV_FILE" "$1" "$2" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text().splitlines() if path.exists() else []
for index, line in enumerate(lines):
    if line.startswith(f"{key}="):
        lines[index] = f"{key}={value}"
        break
else:
    lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n")
PY
}

backup_env_file() {
  if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
  fi
}

placeholder_or_empty() {
  case "${1:-}" in
    ""|replace-with-a-long-random-secret|replace-with-db-password|replace-with-root-password)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

prompt_value() {
  local label="$1"
  local current="${2:-}"
  local secret="${3:-false}"
  local value=""

  if ! is_interactive; then
    echo "$current"
    return 0
  fi

  if [ "$secret" = "true" ]; then
    if [ -n "$current" ]; then
      printf "%s [已设置，回车保留]: " "$label" >&2
    else
      printf "%s: " "$label" >&2
    fi
    read -r -s value
    printf '\n' >&2
    if [ -z "$value" ]; then
      value="$current"
    fi
  else
    if [ -n "$current" ]; then
      printf "%s [%s]: " "$label" "$current" >&2
    else
      printf "%s: " "$label" >&2
    fi
    read -r value
    if [ -z "$value" ]; then
      value="$current"
    fi
  fi

  echo "$value"
}

require_value() {
  local key="$1"
  local value="$2"
  if [ -z "$value" ]; then
    echo "$key 未提供，无法继续。"
    exit 1
  fi
}

ensure_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$PROJECT_DIR/.env.server.example" "$ENV_FILE"
  fi
}

prepare_env() {
  require_command python3
  ensure_env_file
  backup_env_file

  local existing_site_url existing_web_port
  existing_site_url=$(get_env_value SITE_URL)
  existing_web_port=$(get_env_value WEB_PORT)

  local server_host="${SERVER_HOST:-}"
  if [ -z "$server_host" ] && [ -n "$existing_site_url" ]; then
    server_host=$(normalize_host "$existing_site_url")
  fi
  server_host=$(prompt_value "服务器 IP 或主机名" "$server_host")
  server_host=$(normalize_host "$server_host")
  require_value "服务器 IP 或主机名" "$server_host"

  local web_port="${WEB_PORT_OVERRIDE:-${WEB_PORT:-$existing_web_port}}"
  web_port=$(prompt_value "对外端口" "${web_port:-8000}")
  web_port=$(normalize_port "$web_port")
  require_value "对外端口" "$web_port"

  local site_url
  site_url=$(build_origin "$server_host" "$web_port")

  local allowed_hosts="${ALLOWED_HOSTS_OVERRIDE:-$server_host}"
  if is_interactive; then
    allowed_hosts=$(prompt_value "ALLOWED_HOSTS" "$allowed_hosts")
  fi
  require_value "ALLOWED_HOSTS" "$allowed_hosts"

  local csrf_trusted_origins
  csrf_trusted_origins="${CSRF_TRUSTED_ORIGINS_OVERRIDE:-$(build_origin "$server_host" "$web_port")}"
  if is_interactive; then
    csrf_trusted_origins=$(prompt_value "CSRF_TRUSTED_ORIGINS" "$csrf_trusted_origins")
  fi
  require_value "CSRF_TRUSTED_ORIGINS" "$csrf_trusted_origins"

  local secret_key
  secret_key=$(get_env_value SECRET_KEY)
  if placeholder_or_empty "$secret_key"; then
    secret_key=$(generate_secret_key)
  fi

  local db_name db_user db_password mysql_root_password
  db_name="${DB_NAME:-$(get_env_value DB_NAME)}"
  db_user="${DB_USER:-$(get_env_value DB_USER)}"
  db_password="${DB_PASSWORD:-$(get_env_value DB_PASSWORD)}"
  mysql_root_password="${MYSQL_ROOT_PASSWORD:-$(get_env_value MYSQL_ROOT_PASSWORD)}"

  db_name=$(prompt_value "MySQL 数据库名" "${db_name:-xuanor}")
  db_user=$(prompt_value "MySQL 用户名" "${db_user:-xuanor}")
  if placeholder_or_empty "$db_password"; then
    db_password=""
  fi
  if placeholder_or_empty "$mysql_root_password"; then
    mysql_root_password=""
  fi
  db_password=$(prompt_value "MySQL 用户密码" "$db_password" true)
  mysql_root_password=$(prompt_value "MySQL root 密码" "$mysql_root_password" true)
  require_value "DB_NAME" "$db_name"
  require_value "DB_USER" "$db_user"
  require_value "DB_PASSWORD" "$db_password"
  require_value "MYSQL_ROOT_PASSWORD" "$mysql_root_password"

  local realtime_enabled="${CHAT_REALTIME_ENABLED:-$(get_env_value CHAT_REALTIME_ENABLED)}"
  if [ -z "$realtime_enabled" ]; then
    realtime_enabled="False"
  fi
  if is_interactive; then
    realtime_enabled=$(prompt_value "开启实时聊天 (True/False)" "$realtime_enabled")
  fi
  case "$realtime_enabled" in
    True|true|1|yes|on)
      realtime_enabled="True"
      ;;
    *)
      realtime_enabled="False"
      ;;
  esac

  set_env_value DEPLOY_ENV server
  set_env_value DEBUG False
  set_env_value SECRET_KEY "$secret_key"
  set_env_value ALLOWED_HOSTS "$allowed_hosts"
  set_env_value CSRF_TRUSTED_ORIGINS "$csrf_trusted_origins"
  set_env_value USE_X_FORWARDED_HOST False
  set_env_value SECURE_SSL_REDIRECT False
  set_env_value SESSION_COOKIE_SECURE False
  set_env_value CSRF_COOKIE_SECURE False
  set_env_value SECURE_HSTS_SECONDS 0
  set_env_value SECURE_HSTS_INCLUDE_SUBDOMAINS False
  set_env_value SECURE_HSTS_PRELOAD False
  set_env_value SECURE_REFERRER_POLICY same-origin
  set_env_value SECURE_CONTENT_TYPE_NOSNIFF True
  set_env_value SITE_URL "$site_url"
  set_env_value WEB_PORT "$web_port"
  set_env_value DB_ENGINE mysql
  set_env_value DB_NAME "$db_name"
  set_env_value DB_USER "$db_user"
  set_env_value DB_PASSWORD "$db_password"
  set_env_value DB_HOST db
  set_env_value DB_PORT 3306
  set_env_value MYSQL_ROOT_PASSWORD "$mysql_root_password"
  set_env_value CHAT_REALTIME_ENABLED "$realtime_enabled"

  if [ "$realtime_enabled" = "True" ]; then
    set_env_value CHANNEL_LAYER_BACKEND redis
    set_env_value REDIS_URL redis://redis:6379/1
  else
    set_env_value CHANNEL_LAYER_BACKEND memory
    set_env_value REDIS_URL redis://redis:6379/1
  fi
}

run_deploy() {
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" check-server
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" deploy-server
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" status
}

print_summary() {
  echo "一键直连部署脚本执行完成。"
  echo "ENV_FILE: $ENV_FILE"
}

usage() {
  echo "用法: bash deploy/one-click-server.sh [prepare|deploy]"
  echo "默认 deploy：准备 .env.server 后执行 check-server + deploy-server + status"
}

require_command bash
require_command cp

case "$MODE" in
  prepare)
    prepare_env
    print_summary
    ;;
  deploy)
    prepare_env
    run_deploy
    print_summary
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac

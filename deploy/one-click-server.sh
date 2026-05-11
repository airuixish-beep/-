#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"

MODE="${1:-deploy}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.server}"
ENV_WAS_CREATED=false

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1"
    exit 1
  }
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

generate_password() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
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

is_placeholder_host() {
  [ "${1:-}" = "auto-detect-host" ]
}

is_loopback_host() {
  python3 - "$1" <<'PY'
import ipaddress
import sys
value = sys.argv[1].strip().lower()
if not value:
    raise SystemExit(1)
if value == 'localhost':
    raise SystemExit(0)
try:
    ip = ipaddress.ip_address(value)
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if ip.is_loopback else 1)
PY
}

first_list_value() {
  python3 - "$1" <<'PY'
import sys
values = [part.strip() for part in sys.argv[1].split(',') if part.strip()]
if values:
    print(values[0])
PY
}

build_allowed_hosts() {
  python3 - "$1" <<'PY'
import sys
host = sys.argv[1].strip()
values = []
for candidate in [host, '127.0.0.1', 'localhost']:
    if candidate and candidate not in values:
        values.append(candidate)
print(','.join(values))
PY
}

build_trusted_origins() {
  python3 - "$1" "$2" <<'PY'
import sys
host = sys.argv[1].strip()
port = sys.argv[2].strip()
values = []
for candidate in [host, '127.0.0.1', 'localhost']:
    if not candidate:
        continue
    if port == '80':
        origin = f'http://{candidate}'
    else:
        origin = f'http://{candidate}:{port}'
    if origin not in values:
        values.append(origin)
print(','.join(values))
PY
}

port_is_free() {
  python3 - "$1" <<'PY'
import socket
import sys
port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(('0.0.0.0', port))
except OSError:
    raise SystemExit(1)
else:
    sock.close()
    raise SystemExit(0)
PY
}

detect_machine_ip() {
  python3 - <<'PY'
import socket
candidates = []
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(('8.8.8.8', 80))
    ip = sock.getsockname()[0]
    if ip and not ip.startswith('127.'):
        candidates.append(ip)
    sock.close()
except OSError:
    pass
try:
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    if ip and not ip.startswith('127.') and ip not in candidates:
        candidates.append(ip)
except OSError:
    pass
if candidates:
    print(candidates[0])
PY
}

detect_server_host() {
  local server_host="${SERVER_HOST:-}"
  if [ -n "$server_host" ]; then
    normalize_host "$server_host"
    return 0
  fi

  local existing_site_url=""
  existing_site_url=$(get_env_value SITE_URL)
  if [ "$ENV_WAS_CREATED" = "false" ] && [ -n "$existing_site_url" ]; then
    local existing_host=""
    existing_host=$(normalize_host "$existing_site_url")
    if [ -n "$existing_host" ] && ! is_loopback_host "$existing_host" && ! is_placeholder_host "$existing_host"; then
      printf '%s' "$existing_host"
      return 0
    fi
  fi

  local existing_allowed_hosts=""
  existing_allowed_hosts=$(get_env_value ALLOWED_HOSTS)
  if [ "$ENV_WAS_CREATED" = "false" ] && [ -n "$existing_allowed_hosts" ]; then
    local first_host=""
    first_host=$(first_list_value "$existing_allowed_hosts")
    if [ -n "$first_host" ] && ! is_loopback_host "$first_host" && ! is_placeholder_host "$first_host"; then
      printf '%s' "$first_host"
      return 0
    fi
  fi

  local machine_ip=""
  machine_ip=$(detect_machine_ip)
  if [ -n "$machine_ip" ]; then
    printf '%s' "$machine_ip"
    return 0
  fi

  if [ -n "$existing_site_url" ]; then
    local fallback_host=""
    fallback_host=$(normalize_host "$existing_site_url")
    if [ -n "$fallback_host" ]; then
      printf '%s' "$fallback_host"
      return 0
    fi
  fi

  printf '127.0.0.1'
}

detect_web_port() {
  local explicit_port="${WEB_PORT_OVERRIDE:-${WEB_PORT:-}}"
  if [ -n "$explicit_port" ]; then
    normalize_port "$explicit_port"
    return 0
  fi

  local existing_port=""
  existing_port=$(get_env_value WEB_PORT)
  if [ "$ENV_WAS_CREATED" = "false" ] && [ -n "$existing_port" ]; then
    normalize_port "$existing_port"
    return 0
  fi

  local candidate
  for candidate in 8000 8080 8888 18000; do
    if port_is_free "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
  done

  printf '8000'
}

ensure_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$PROJECT_DIR/.env.server.example" "$ENV_FILE"
    ENV_WAS_CREATED=true
  fi
}

prepare_env() {
  require_command python3
  ensure_env_file
  backup_env_file

  local server_host web_port site_url allowed_hosts csrf_trusted_origins
  server_host=$(detect_server_host)
  require_value "服务器 IP 或主机名" "$server_host"

  web_port=$(detect_web_port)
  require_value "对外端口" "$web_port"

  site_url=$(build_origin "$server_host" "$web_port")
  allowed_hosts="${ALLOWED_HOSTS_OVERRIDE:-$(build_allowed_hosts "$server_host") }"
  allowed_hosts="${allowed_hosts% }"
  csrf_trusted_origins="${CSRF_TRUSTED_ORIGINS_OVERRIDE:-$(build_trusted_origins "$server_host" "$web_port") }"
  csrf_trusted_origins="${csrf_trusted_origins% }"

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

  db_name="${db_name:-xuanor}"
  db_user="${db_user:-xuanor}"
  if placeholder_or_empty "$db_password"; then
    db_password=$(generate_password)
  fi
  if placeholder_or_empty "$mysql_root_password"; then
    mysql_root_password=$(generate_password)
  fi

  local realtime_enabled="${CHAT_REALTIME_ENABLED:-$(get_env_value CHAT_REALTIME_ENABLED)}"
  if [ -z "$realtime_enabled" ]; then
    realtime_enabled="False"
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
  set_env_value TRUST_PROXY_HEADERS False
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

require_value() {
  local key="$1"
  local value="$2"
  if [ -z "$value" ]; then
    echo "$key 未提供，无法继续。"
    exit 1
  fi
}

run_deploy() {
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" check-server
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" bootstrap-server
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" status
}

print_summary() {
  echo "一键直连部署脚本执行完成。"
  echo "ENV_FILE: $ENV_FILE"
  echo "访问地址: $(get_env_value SITE_URL)/"
}

usage() {
  echo "用法: bash deploy/one-click-server.sh [prepare|deploy]"
  echo "默认 deploy：零输入生成 .env.server 后执行 check-server + bootstrap-server + status"
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

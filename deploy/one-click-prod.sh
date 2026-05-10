#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"

MODE="${1:-deploy}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
CERT_DIR="$PROJECT_DIR/deploy/certs"
FULLCHAIN_TARGET="$CERT_DIR/fullchain.pem"
PRIVKEY_TARGET="$CERT_DIR/privkey.pem"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令: $1"
    exit 1
  }
}

is_interactive() {
  [ -t 0 ]
}

normalize_domain() {
  local value="$1"
  value="${value#http://}"
  value="${value#https://}"
  value="${value%%/*}"
  printf '%s' "$value"
}

extract_domain_from_url() {
  local value="$1"
  if [ -z "$value" ]; then
    return 0
  fi
  normalize_domain "$value"
}

derive_hosts() {
  local domain="$1"
  if [ -z "$domain" ]; then
    return 0
  fi

  local bare="$domain"
  if [[ "$domain" == www.* ]]; then
    bare="${domain#www.}"
  fi

  if [ "$domain" = "$bare" ]; then
    printf '%s,%s' "$bare" "www.$bare"
  else
    printf '%s,%s' "$bare" "$domain"
  fi
}

derive_origins() {
  local hosts="$1"
  local scheme="$2"
  python3 - "$hosts" "$scheme" <<'PY'
import sys
hosts = [host.strip() for host in sys.argv[1].split(',') if host.strip()]
scheme = sys.argv[2]
print(','.join(f'{scheme}://{host}' for host in hosts))
PY
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
    cp "$PROJECT_DIR/.env.production.example" "$ENV_FILE"
  fi
}

ensure_certificate() {
  local target="$1"
  local label="$2"
  local source_path="$3"

  if [ -f "$target" ] && [ -s "$target" ]; then
    return 0
  fi

  source_path=$(prompt_value "$label 源文件路径" "$source_path")
  require_value "$label 源文件路径" "$source_path"
  [ -f "$source_path" ] || {
    echo "$label 源文件不存在: $source_path"
    exit 1
  }

  if [ "$(realpath "$source_path")" = "$(realpath -m "$target")" ]; then
    return 0
  fi

  install -m 600 "$source_path" "$target"
}

prepare_env() {
  require_command python3
  mkdir -p "$CERT_DIR"
  ensure_env_file
  backup_env_file

  local existing_domain existing_hosts existing_origins existing_site_url existing_tls_enabled
  existing_site_url=$(get_env_value SITE_URL)
  existing_domain=$(extract_domain_from_url "$existing_site_url")
  existing_hosts=$(get_env_value ALLOWED_HOSTS)
  existing_origins=$(get_env_value CSRF_TRUSTED_ORIGINS)
  existing_tls_enabled=$(get_env_value TLS_ENABLED)

  local domain="${SITE_DOMAIN:-$existing_domain}"
  domain=$(prompt_value "站点主域名" "$domain")
  domain=$(normalize_domain "$domain")
  require_value "站点主域名" "$domain"

  local domain_changed=false
  if [ "$domain" != "$existing_domain" ]; then
    domain_changed=true
  fi

  local tls_enabled="${TLS_ENABLED:-$existing_tls_enabled}"
  if [ -z "$tls_enabled" ]; then
    tls_enabled="False"
  fi
  if is_interactive; then
    tls_enabled=$(prompt_value "启用 HTTPS 证书 (True/False)" "$tls_enabled")
  fi
  case "$tls_enabled" in
    True|true|1|yes|on)
      tls_enabled="True"
      ;;
    *)
      tls_enabled="False"
      ;;
  esac

  local site_scheme="http"
  local nginx_conf_file="nginx.http.conf"
  if [ "$tls_enabled" = "True" ]; then
    site_scheme="https"
    nginx_conf_file="nginx.https.conf"
  fi

  local site_url="${SITE_URL_OVERRIDE:-$existing_site_url}"
  if [ -z "${SITE_URL_OVERRIDE:-}" ] && { [ "$domain_changed" = "true" ] || [ -z "$site_url" ] || [[ "$site_url" != ${site_scheme}://* ]]; }; then
    site_url="${site_scheme}://$domain"
  fi

  local allowed_hosts="${ALLOWED_HOSTS_OVERRIDE:-$existing_hosts}"
  if [ -z "${ALLOWED_HOSTS_OVERRIDE:-}" ] && { [ "$domain_changed" = "true" ] || [ -z "$allowed_hosts" ]; }; then
    allowed_hosts=$(derive_hosts "$domain")
  fi
  if is_interactive; then
    allowed_hosts=$(prompt_value "ALLOWED_HOSTS" "$allowed_hosts")
  fi
  require_value "ALLOWED_HOSTS" "$allowed_hosts"

  local csrf_trusted_origins="${CSRF_TRUSTED_ORIGINS_OVERRIDE:-$existing_origins}"
  if [ -z "${CSRF_TRUSTED_ORIGINS_OVERRIDE:-}" ] && { [ "$domain_changed" = "true" ] || [ -z "$csrf_trusted_origins" ] || { [ "$site_scheme" = "http" ] && [[ "$csrf_trusted_origins" == https://* ]]; } || { [ "$site_scheme" = "https" ] && [[ "$csrf_trusted_origins" == http://* ]]; }; }; then
    csrf_trusted_origins=$(derive_origins "$allowed_hosts" "$site_scheme")
  fi
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
    realtime_enabled="True"
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

  local secure_ssl_redirect=False
  local session_cookie_secure=False
  local csrf_cookie_secure=False
  local secure_hsts_seconds=0
  local secure_hsts_include_subdomains=False
  local secure_hsts_preload=False
  local proxy_healthcheck_url="${site_scheme}://127.0.0.1/healthz/live"

  if [ "$tls_enabled" = "True" ]; then
    secure_ssl_redirect=True
    session_cookie_secure=True
    csrf_cookie_secure=True
    secure_hsts_seconds=31536000
    secure_hsts_include_subdomains=True
    secure_hsts_preload=True
  fi

  set_env_value DEPLOY_ENV prod
  set_env_value DEBUG False
  set_env_value TLS_ENABLED "$tls_enabled"
  set_env_value NGINX_CONF_FILE "$nginx_conf_file"
  set_env_value PROXY_HEALTHCHECK_URL "$proxy_healthcheck_url"
  set_env_value SECRET_KEY "$secret_key"
  set_env_value ALLOWED_HOSTS "$allowed_hosts"
  set_env_value CSRF_TRUSTED_ORIGINS "$csrf_trusted_origins"
  set_env_value USE_X_FORWARDED_HOST True
  set_env_value SECURE_SSL_REDIRECT "$secure_ssl_redirect"
  set_env_value SESSION_COOKIE_SECURE "$session_cookie_secure"
  set_env_value CSRF_COOKIE_SECURE "$csrf_cookie_secure"
  set_env_value SECURE_HSTS_SECONDS "$secure_hsts_seconds"
  set_env_value SECURE_HSTS_INCLUDE_SUBDOMAINS "$secure_hsts_include_subdomains"
  set_env_value SECURE_HSTS_PRELOAD "$secure_hsts_preload"
  set_env_value SECURE_REFERRER_POLICY same-origin
  set_env_value SECURE_CONTENT_TYPE_NOSNIFF True
  set_env_value SITE_URL "$site_url"
  set_env_value WEB_PORT 8000
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

  if [ "$tls_enabled" = "True" ]; then
    ensure_certificate "$FULLCHAIN_TARGET" "fullchain.pem" "${FULLCHAIN_SOURCE:-}"
    ensure_certificate "$PRIVKEY_TARGET" "privkey.pem" "${PRIVKEY_SOURCE:-}"
  fi
}

run_deploy() {
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" check
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" deploy
  ENV_FILE="$ENV_FILE" bash "$PROJECT_DIR/deploy/auto-deploy.sh" status
}

print_summary() {
  echo "一键部署脚本执行完成。"
  echo "ENV_FILE: $ENV_FILE"
  echo "证书目录: $CERT_DIR"
}

usage() {
  echo "用法: bash deploy/one-click-prod.sh [prepare|deploy]"
  echo "默认 deploy：准备 .env 后执行 check + deploy + status；仅 TLS_ENABLED=True 时要求证书"
}

require_command bash
require_command cp
require_command install

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

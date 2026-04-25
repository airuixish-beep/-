#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"

MODE="${1:-deploy}"
COMPOSE_ARGS=(-f docker-compose.yml)
COMPOSE_PROFILES=()
PROXY_SERVICE=proxy
ENV_FILE="${ENV_FILE:-}"

check_docker() {
  command -v docker >/dev/null 2>&1 || { echo "Docker 未安装，请先安装 Docker Desktop 或 Docker Engine"; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "Docker Compose 不可用，请确认 docker compose 可执行"; exit 1; }
}

ensure_env_file_path() {
  if [ -z "$ENV_FILE" ]; then
    if [ "${DEPLOY_ENV:-prod}" = "local" ]; then
      ENV_FILE="$PROJECT_DIR/.env.local"
    else
      ENV_FILE="$PROJECT_DIR/.env"
    fi
  fi
}

compose_cmd() {
  export ENV_FILE
  docker compose --env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}" "$@"
}

is_true() {
  case "${1:-}" in
    True|true|1|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

ensure_env() {
  if [ ! -f "$ENV_FILE" ]; then
    local example_file="$PROJECT_DIR/.env.example"
    if [ "${DEPLOY_ENV:-prod}" = "prod" ] && [ -f "$PROJECT_DIR/.env.production.example" ]; then
      example_file="$PROJECT_DIR/.env.production.example"
    elif [ "${DEPLOY_ENV:-prod}" = "local" ] && [ -f "$PROJECT_DIR/.env.local.example" ]; then
      example_file="$PROJECT_DIR/.env.local.example"
    fi
    cp "$example_file" "$ENV_FILE"
    echo "已从 ${example_file##*/} 生成 ${ENV_FILE##*/}，请先填入真实部署配置。"
    exit 1
  fi
}

load_env() {
  set -a
  . "$ENV_FILE"
  set +a
}

configure_profiles() {
  COMPOSE_ARGS=(-f docker-compose.yml)
  PROXY_SERVICE=proxy
  COMPOSE_PROFILES=()

  if [ "${DEPLOY_ENV:-prod}" = "local" ]; then
    export COMPOSE_PROJECT_NAME="xuanor_local"
  else
    unset COMPOSE_PROJECT_NAME || true
  fi

  if [ "${DEPLOY_ENV:-prod}" = "local" ] && [ -f "$PROJECT_DIR/docker-compose.local.yml" ]; then
    COMPOSE_ARGS+=( -f docker-compose.local.yml )
  fi

  if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
    if [ -f "$PROJECT_DIR/docker-compose.prod.yml" ]; then
      COMPOSE_ARGS+=( -f docker-compose.prod.yml )
    fi
    COMPOSE_PROFILES+=(prod)
  fi

  if is_true "${CHAT_REALTIME_ENABLED:-false}"; then
    COMPOSE_PROFILES+=(realtime)
  fi

  if [ ${#COMPOSE_PROFILES[@]} -gt 0 ]; then
    COMPOSE_PROFILES=$(IFS=,; echo "${COMPOSE_PROFILES[*]}")
    export COMPOSE_PROFILES
  else
    unset COMPOSE_PROFILES || true
  fi

  if compose_cmd config --services >/tmp/xuanor-compose-services.txt 2>/dev/null; then
    if grep -qx 'proxy' /tmp/xuanor-compose-services.txt; then
      PROXY_SERVICE=proxy
    elif grep -qx 'nginx' /tmp/xuanor-compose-services.txt; then
      PROXY_SERVICE=nginx
    fi
  fi
}

ensure_prod_requirements() {
  if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
    [ -f "$PROJECT_DIR/deploy/certs/fullchain.pem" ] || { echo "缺少证书文件: deploy/certs/fullchain.pem"; exit 1; }
    [ -f "$PROJECT_DIR/deploy/certs/privkey.pem" ] || { echo "缺少证书文件: deploy/certs/privkey.pem"; exit 1; }
  fi
}

validate_env() {
  [ -n "${SECRET_KEY:-}" ] || { echo "SECRET_KEY 未配置"; exit 1; }
  [ "${SECRET_KEY}" != "replace-with-a-long-random-secret" ] || { echo "SECRET_KEY 仍是示例值，请替换"; exit 1; }
  [ -n "${ALLOWED_HOSTS:-}" ] || { echo "ALLOWED_HOSTS 未配置"; exit 1; }
  [ -n "${CSRF_TRUSTED_ORIGINS:-}" ] || { echo "CSRF_TRUSTED_ORIGINS 未配置"; exit 1; }
  [ -n "${SITE_URL:-}" ] || { echo "SITE_URL 未配置"; exit 1; }
  if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
    [ "${DEBUG:-false}" = "False" ] || [ "${DEBUG:-false}" = "false" ] || { echo "生产环境必须设置 DEBUG=False"; exit 1; }
    case "${SITE_URL}" in
      https://*) ;;
      *) echo "生产环境 SITE_URL 必须使用 https://"; exit 1 ;;
    esac
  fi
}

print_local_hints() {
  echo "本地 Docker 部署完成。"
  echo "首页:  ${SITE_URL}/"
  echo "后台:  ${SITE_URL}/admin/"
  echo "如需演示数据，可执行: ENV_FILE=${ENV_FILE} docker compose ${COMPOSE_ARGS[*]} run --rm web python manage.py seed_product_demo"
}

run_release_steps() {
  local release_services=(db)
  if is_true "${CHAT_REALTIME_ENABLED:-false}"; then
    release_services+=(redis)
  fi

  compose_cmd up --build -d "${release_services[@]}"
  ensure_local_test_database
  compose_cmd run --rm web python manage.py migrate --noinput
  compose_cmd run --rm web python manage.py collectstatic --noinput
}

ensure_local_test_database() {
  if [ "${DEPLOY_ENV:-prod}" != "local" ] || [ "${DB_ENGINE:-sqlite}" != "mysql" ]; then
    return
  fi

  local test_db_name="${DB_TEST_NAME:-${DB_NAME:-}}"
  [ -n "$test_db_name" ] || return

  compose_cmd exec -T db mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" -e "CREATE DATABASE IF NOT EXISTS \`${test_db_name}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON \`${test_db_name}\`.* TO '${DB_USER}'@'%'; FLUSH PRIVILEGES;" >/dev/null
}

run_health_checks() {
  compose_cmd run --rm web python manage.py check
  if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
    compose_cmd run --rm web python manage.py check --deploy --fail-level WARNING
  fi
}

run_local_bootstrap() {
  compose_cmd run --build --rm web python manage.py seed_product_demo
  compose_cmd run --build --rm web python manage.py ensure_local_admin --username admin --email admin@example.com --password admin123456
}

start_core_services() {
  local services=(web)
  if is_true "${CHAT_REALTIME_ENABLED:-false}"; then
    services+=(redis)
  fi
  compose_cmd up --build -d "${services[@]}"
}

case "$MODE" in
  deploy)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    ensure_prod_requirements
    validate_env
    run_release_steps
    run_health_checks
    start_core_services
    if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
      compose_cmd up -d "$PROXY_SERVICE"
    fi
    compose_cmd ps
    if [ "${DEPLOY_ENV:-prod}" = "local" ]; then
      print_local_hints
    else
      echo "部署完成。"
      echo "首页:  ${SITE_URL}/"
      echo "后台:  ${SITE_URL}/admin/"
    fi
    ;;
  deploy-local)
    export DEPLOY_ENV=local
    ENV_FILE="$PROJECT_DIR/.env.local"
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    validate_env
    run_release_steps
    run_health_checks
    start_core_services
    compose_cmd ps
    print_local_hints
    ;;
  bootstrap-local)
    export DEPLOY_ENV=local
    ENV_FILE="$PROJECT_DIR/.env.local"
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    validate_env
    run_release_steps
    run_health_checks
    run_local_bootstrap
    start_core_services
    compose_cmd ps
    print_local_hints
    echo "本地管理员: admin / admin123456"
    ;;
  migrate)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    run_release_steps
    ;;
  check)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    ensure_prod_requirements
    validate_env
    run_health_checks
    ;;
  exec)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    shift
    [ "$#" -gt 0 ] || { echo "用法: bash deploy/auto-deploy.sh exec <command>"; exit 1; }
    compose_cmd exec web "$@"
    ;;
  status)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    compose_cmd ps
    ;;
  logs)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    compose_cmd logs -f --tail=100
    ;;
  restart)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    compose_cmd restart
    compose_cmd ps
    ;;
  stop)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    compose_cmd down
    ;;
  destroy)
    check_docker
    ensure_env_file_path
    ensure_env
    load_env
    configure_profiles
    compose_cmd down -v --remove-orphans
    ;;
  *)
    echo "用法: bash deploy/auto-deploy.sh [deploy|deploy-local|bootstrap-local|migrate|check|exec <command>|status|logs|restart|stop|destroy]"
    exit 1
    ;;
esac

#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"

MODE="${1:-deploy}"
COMPOSE_ARGS=(-f docker-compose.yml)
COMPOSE_PROFILES=()

check_docker() {
  command -v docker >/dev/null 2>&1 || { echo "Docker 未安装，请先安装 Docker Desktop 或 Docker Engine"; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "Docker Compose 不可用，请确认 docker compose 可执行"; exit 1; }
}

compose_cmd() {
  docker compose "${COMPOSE_ARGS[@]}" "$@"
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
  if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "已从 .env.example 生成 .env，请先填入真实生产配置。"
    exit 1
  fi
}

load_env() {
  set -a
  . "$PROJECT_DIR/.env"
  set +a
}

configure_profiles() {
  COMPOSE_PROFILES=()
  if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
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

run_release_steps() {
  local release_services=(db)
  if is_true "${CHAT_REALTIME_ENABLED:-false}"; then
    release_services+=(redis)
  fi

  compose_cmd up --build -d "${release_services[@]}"
  compose_cmd run --rm web python manage.py migrate --noinput
  compose_cmd run --rm web python manage.py collectstatic --noinput
}

run_health_checks() {
  compose_cmd run --rm web python manage.py check
  if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
    compose_cmd run --rm web python manage.py check --deploy --fail-level WARNING
  fi
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
    ensure_env
    load_env
    configure_profiles
    ensure_prod_requirements
    validate_env
    run_release_steps
    run_health_checks
    start_core_services
    if [ "${DEPLOY_ENV:-prod}" = "prod" ]; then
      compose_cmd up -d proxy
    fi
    compose_cmd ps
    echo "部署完成。"
    echo "首页:  ${SITE_URL}/"
    echo "后台:  ${SITE_URL}/admin/"
    ;;
  migrate)
    check_docker
    ensure_env
    load_env
    configure_profiles
    run_release_steps
    ;;
  check)
    check_docker
    ensure_env
    load_env
    configure_profiles
    ensure_prod_requirements
    validate_env
    run_health_checks
    ;;
  exec)
    check_docker
    ensure_env
    load_env
    configure_profiles
    shift
    [ "$#" -gt 0 ] || { echo "用法: bash deploy/auto-deploy.sh exec <command>"; exit 1; }
    compose_cmd exec web "$@"
    ;;
  status)
    check_docker
    ensure_env
    load_env
    configure_profiles
    compose_cmd ps
    ;;
  logs)
    check_docker
    ensure_env
    load_env
    configure_profiles
    compose_cmd logs -f --tail=100
    ;;
  restart)
    check_docker
    ensure_env
    load_env
    configure_profiles
    compose_cmd restart
    compose_cmd ps
    ;;
  stop)
    check_docker
    ensure_env
    load_env
    configure_profiles
    compose_cmd down
    ;;
  destroy)
    check_docker
    ensure_env
    load_env
    configure_profiles
    compose_cmd down -v --remove-orphans
    ;;
  *)
    echo "用法: bash deploy/auto-deploy.sh [deploy|migrate|check|exec <command>|status|logs|restart|stop|destroy]"
    exit 1
    ;;
esac

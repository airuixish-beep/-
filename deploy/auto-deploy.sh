#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$PROJECT_DIR"

MODE="${1:-deploy}"

check_docker() {
  command -v docker >/dev/null 2>&1 || { echo "Docker 未安装，请先安装 Docker Desktop 或 Docker Engine"; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "Docker Compose 不可用，请确认 docker compose 可执行"; exit 1; }
}

ensure_env() {
  if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "已从 .env.example 生成 .env，请按需修改配置。"
  fi
}

case "$MODE" in
  deploy)
    check_docker
    ensure_env
    docker compose up --build -d
    echo "部署完成。"
    echo "首页:  http://127.0.0.1:8000/"
    echo "产品:  http://127.0.0.1:8000/products/"
    echo "后台:  http://127.0.0.1:8000/admin/"
    ;;
  status)
    check_docker
    docker compose ps
    ;;
  logs)
    check_docker
    docker compose logs -f --tail=100
    ;;
  restart)
    check_docker
    docker compose restart
    docker compose ps
    ;;
  stop)
    check_docker
    docker compose down
    ;;
  *)
    echo "用法: bash deploy/auto-deploy.sh [deploy|status|logs|restart|stop]"
    exit 1
    ;;
esac

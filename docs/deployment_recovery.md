# Xuanor 部署恢复说明

## 当前已确认的问题

1. 公网域名 `www.xuanor.com` 当前解析异常，外部探测解析到 `198.18.11.199`，并且 HTTPS 握手失败。
2. 本地源码可正常通过 Django 检查；`/admin/` 与 `/admin/support-chat/` 路由正常。
3. `support_chat` 模块 42 个测试全部通过，说明后台客服主流程代码本身没有明显致命故障。
4. 之前部署脚本没有在生产环境自动加载 `docker-compose.prod.yml`，并且 prod 覆盖文件里的代理服务命名与主 compose 不一致，存在部署代理层未按预期启动的风险。

## 当前推荐部署方式

现在有三条正式路径：

### 1. 服务器直连 Docker

```bash
bash deploy/one-click-server.sh
```

这是当前推荐主入口：
- 不需要提供域名、证书、数据库密码或 root 密码
- 自动生成 `.env.server`
- 自动生成 `SECRET_KEY`、`DB_PASSWORD`、`MYSQL_ROOT_PASSWORD`
- 自动识别可用主机地址与端口
- 自动执行 `bootstrap-server`，把管理员和演示数据一起初始化

也可以手动执行：

```bash
bash deploy/auto-deploy.sh deploy-server
```

这条路径不需要域名、证书和 nginx 反代，直接把 `web` 暴露到宿主机端口。

### 2. 反代生产模式

```bash
bash deploy/auto-deploy.sh deploy
```

适合后续需要域名、80/443、证书和代理入口的场景。

### 3. 本地开发模式

```bash
bash deploy/auto-deploy.sh deploy-local
```

不要把裸 `docker compose up` 当成正式发布命令。当前脚本会统一负责：

- 加载正确 env 文件
- 选择正确 compose 覆盖层
- 启用需要的 profile
- 先拉起依赖服务，再执行 `migrate` / `collectstatic`
- 等待健康检查通过
- 最后验证首页、后台和静态资源是否真实可访问

## 上线前必须确认

### DNS / CDN
优先级最高：

- 检查 `www.xuanor.com` 的 `A / AAAA / CNAME`
- 确认为什么会解析到 `198.18.11.199`
- 若为错误解析，改为真实源站公网 IP 或正确 CDN CNAME
- 若使用 Cloudflare / 其他 CDN，检查：
  - 代理是否开启
  - 回源地址是否正确
  - SSL 模式是否正确

### 服务器直连模式环境变量
建议 `.env.server` 至少包含：

```env
DEPLOY_ENV=server
DEBUG=False
SECRET_KEY=<强随机值>
ALLOWED_HOSTS=<服务器IP或主机名>
CSRF_TRUSTED_ORIGINS=http://<服务器IP或主机名>:<端口>
USE_X_FORWARDED_HOST=False
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
SITE_URL=http://<服务器IP或主机名>:<端口>
WEB_PORT=<端口>
DB_ENGINE=mysql
DB_NAME=xuanor
DB_USER=xuanor
DB_PASSWORD=<数据库密码>
DB_HOST=db
DB_PORT=3306
MYSQL_ROOT_PASSWORD=<root密码>
CHAT_REALTIME_ENABLED=False
CHANNEL_LAYER_BACKEND=memory
```

### 反代生产模式环境变量
建议 `.env` 至少包含：

```env
DEPLOY_ENV=prod
DEBUG=False
TLS_ENABLED=False
NGINX_CONF_FILE=nginx.http.conf
PROXY_HEALTHCHECK_URL=http://127.0.0.1/healthz/live
SECRET_KEY=<强随机值>
ALLOWED_HOSTS=xuanor.com,www.xuanor.com
CSRF_TRUSTED_ORIGINS=http://xuanor.com,http://www.xuanor.com
SITE_URL=http://www.xuanor.com
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
WEB_PORT=8000
DB_ENGINE=mysql
DB_NAME=xuanor
DB_USER=xuanor
DB_PASSWORD=<数据库密码>
DB_HOST=db
DB_PORT=3306
MYSQL_ROOT_PASSWORD=<root密码>
CHAT_REALTIME_ENABLED=True
CHANNEL_LAYER_BACKEND=redis
REDIS_URL=redis://redis:6379/1
```

### 证书文件
只有反代生产模式切到 HTTPS 时才需要：

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

## 推荐恢复步骤

### 1. 服务器直连 Docker（推荐当前需求）
准备 `.env.server`，或直接执行：

```bash
bash deploy/one-click-server.sh
```

也可以手动执行：

```bash
bash deploy/auto-deploy.sh check-server
bash deploy/auto-deploy.sh deploy-server
```

部署后验证：

```bash
ENV_FILE=.env.server bash deploy/auto-deploy.sh status
ENV_FILE=.env.server bash deploy/auto-deploy.sh logs
curl -I http://<服务器IP>:<端口>/
curl -I http://<服务器IP>:<端口>/admin/
curl -I http://<服务器IP>:<端口>/static/admin/css/base.css
curl -I http://<服务器IP>:<端口>/healthz/live
curl -I http://<服务器IP>:<端口>/healthz/ready
```

### 2. 反代生产模式
先保证：

```bash
dig +short www.xuanor.com
```

返回真实公网入口，而不是 `198.18.*.*`。

基于 `.env.production.example` 生成正式配置，重点确认：

- `DEBUG=False`
- `TLS_ENABLED=False`
- `NGINX_CONF_FILE=nginx.http.conf`
- `CSRF_TRUSTED_ORIGINS`
- `SITE_URL=http://www.xuanor.com`

如果要切到 HTTPS，再把证书放到：

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

并把 `.env` 改成：

- `TLS_ENABLED=True`
- `NGINX_CONF_FILE=nginx.https.conf`
- `PROXY_HEALTHCHECK_URL=https://127.0.0.1/healthz/live`
- `SITE_URL=https://www.xuanor.com`

执行部署：

```bash
bash deploy/auto-deploy.sh deploy
```

脚本自身会在部署流程内验证首页、后台、健康检查和静态资源。

## 如果部署后仍打不开
按模式区分检查：

### server 直连模式
1. `ENV_FILE=.env.server bash deploy/auto-deploy.sh status`
2. `ENV_FILE=.env.server bash deploy/auto-deploy.sh logs`
3. `ss -lntp | grep <端口>`
4. `curl -I http://127.0.0.1:<端口>/healthz/live`
5. 安全组 / 防火墙是否放行 `WEB_PORT`

### 反代生产模式
1. `bash deploy/auto-deploy.sh status`
2. `bash deploy/auto-deploy.sh logs`
3. `curl -I http://www.xuanor.com/healthz/live` 或对应的 `https://`
4. 80/443 是否监听
5. 仅 HTTPS 模式下再检查证书路径是否挂载成功
6. DNS 是否仍然指错
7. CDN 是否回源失败

## 当前判断

现在最像根因的是：

- **公网 DNS / CDN 入口异常**
- **之前生产部署脚本与 prod compose 不一致，导致代理层存在未正确启动风险**

后台代码本身目前没有发现阻断性错误。

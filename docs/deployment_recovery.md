# Xuanor 部署恢复说明

## 当前已确认的问题

1. 公网域名 `www.xuanor.com` 当前解析异常，外部探测解析到 `198.18.11.199`，并且 HTTPS 握手失败。
2. 本地源码可正常通过 Django 检查；`/admin/` 与 `/admin/support-chat/` 路由正常。
3. `support_chat` 模块 42 个测试全部通过，说明后台客服主流程代码本身没有明显致命故障。
4. 之前部署脚本没有在生产环境自动加载 `docker-compose.prod.yml`，并且 prod 覆盖文件里的代理服务命名与主 compose 不一致，存在部署代理层未按预期启动的风险。

## 当前推荐生产部署方式

生产环境统一使用：

```bash
bash deploy/auto-deploy.sh deploy
```

不要把裸 `docker compose up` 当成正式发布命令。当前脚本会统一负责：

- 加载正确 env 文件
- 加载 `docker-compose.prod.yml`
- 启用 `prod` / `realtime` profile
- 先拉起依赖服务，再执行 `migrate` / `collectstatic`
- 等待 `web` / `proxy` readiness
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

### 生产环境变量
建议生产 `.env` 至少包含：

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
当 `TLS_ENABLED=False` 时，不需要准备证书。

只有切换到 HTTPS 模式时才需要：

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

## 推荐恢复步骤

### 1. 修正 DNS
先保证：

```bash
dig +short www.xuanor.com
```

返回真实公网入口，而不是 `198.18.*.*`。

### 2. 准备生产 .env
基于 `.env.production.example` 生成正式配置，重点确认：

- `DEBUG=False`
- `TLS_ENABLED=False`
- `NGINX_CONF_FILE=nginx.http.conf`
- `CSRF_TRUSTED_ORIGINS`
- `SITE_URL=http://www.xuanor.com`

### 3. 准备证书（仅 HTTPS 模式）
如果要切到 HTTPS，再把证书放到：

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

并把 `.env` 改成：

- `TLS_ENABLED=True`
- `NGINX_CONF_FILE=nginx.https.conf`
- `PROXY_HEALTHCHECK_URL=https://127.0.0.1/healthz/live`
- `SITE_URL=https://www.xuanor.com`

### 4. 执行部署

```bash
bash deploy/auto-deploy.sh deploy
```

### 5. 部署后验证

HTTP-only 模式：

```bash
bash deploy/auto-deploy.sh status
bash deploy/auto-deploy.sh logs
curl -I http://www.xuanor.com/
curl -I http://www.xuanor.com/admin/
curl -I http://www.xuanor.com/static/admin/css/base.css
curl -I http://www.xuanor.com/healthz/live
curl -I http://www.xuanor.com/healthz/ready
```

HTTPS 模式把上面的 `http://` 换成 `https://` 即可。

脚本自身会在部署流程内验证首页、后台、健康检查和静态资源；上面的命令用于二次复核。

## 如果部署后仍打不开
按顺序检查：

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

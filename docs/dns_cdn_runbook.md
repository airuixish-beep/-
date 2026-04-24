# Xuanor DNS / CDN 排查 Runbook

## 目标
恢复 `https://www.xuanor.com` 和后台 `https://www.xuanor.com/admin/` 的公网可访问性。

## 已知现象
- 外部探测时，`www.xuanor.com` 解析到 `198.18.11.199`
- HTTPS 握手失败
- 后台与首页均无法从公网正常访问

## 一次只做一层排查
顺序不要乱：

1. DNS 记录
2. CDN / 代理
3. 源站可用性
4. 证书 / TLS
5. 应用层后台

---

## 1. DNS 检查
在本地或服务器执行：

```bash
dig +short xuanor.com
dig +short www.xuanor.com
nslookup xuanor.com
nslookup www.xuanor.com
```

### 正常预期
- 指向真实源站公网 IP，或
- 指向你使用的 CDN 正确 CNAME

### 异常信号
- 返回 `198.18.x.x`
- 指向未知 IP
- `www` 与根域名记录不一致
- 同时存在冲突的 `A` / `AAAA` / `CNAME`

### 后台要核对的记录
- `@`
- `www`
- `A`
- `AAAA`
- `CNAME`
- 是否开启代理/CDN 小云朵/橙云之类

---

## 2. CDN / Cloudflare 检查
如果你用了 Cloudflare、EdgeOne、阿里云 CDN、腾讯云 CDN：

### 要确认
- `www.xuanor.com` 是否被代理
- 源站 IP 是否正确
- 回源协议是 HTTP 还是 HTTPS
- SSL 模式是否正确
- 是否启用了拦截规则 / WAF / 地区限制 / IP 白名单

### Cloudflare 常用检查项
- DNS → `www` 记录是否正确
- SSL/TLS → 建议源站有证书时用 `Full (strict)`
- Rules / WAF → 是否拦截了正常请求
- Origin Rules / Tunnel → 是否回源到了错误目标

---

## 3. 源站检查
如果你有服务器权限，在服务器执行：

```bash
ss -lntp | grep -E ':80|:443'
curl -I http://127.0.0.1
curl -Ik https://127.0.0.1
```

### 正常预期
- 80 和 443 至少有一个在监听
- 本机请求能拿到 Nginx / 站点响应

### 如果是 Docker 部署
```bash
docker compose ps
docker compose logs --tail=100 proxy
docker compose logs --tail=100 web
```

---

## 4. 证书 / TLS 检查
检查证书文件是否存在：

```bash
ls -l deploy/certs/fullchain.pem
aaa=deploy/certs/privkey.pem; ls -l "$aaa"
```

检查 Nginx 配置后重载：

```bash
nginx -t
```

### 异常信号
- 证书文件缺失
- Nginx 配置语法错误
- 源站只监听 HTTP，没有 HTTPS
- CDN 用 HTTPS 回源，但源站证书无效

---

## 5. 应用层检查
当 1-4 都正常后，再看 Django 后台：

```bash
curl -I https://www.xuanor.com/admin/
```

如果返回 302/200，再继续看：
- 登录页是否正常打开
- 静态资源是否 200
- 后台表单是否有 CSRF 报错

### 生产环境变量必须核对
- `DEBUG=False`
- `ALLOWED_HOSTS=xuanor.com,www.xuanor.com`
- `CSRF_TRUSTED_ORIGINS=https://xuanor.com,https://www.xuanor.com`
- `SITE_URL=https://www.xuanor.com`

---

## 最短恢复路径
1. 修正 `www.xuanor.com` DNS
2. 确认 CDN 回源正确
3. 确认代理 `proxy` 已运行
4. 确认证书挂载正常
5. 再访问 `/admin/`

如果第 1 步不对，后面都不用继续。

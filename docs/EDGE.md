# MZTLAB · Scene 接入层（nginx）配置与核对

> **适用版本：3.0.0**
>
> 本文是接入层的**唯一文档**：写清部署方（运维）必须满足的路由、转发头、体积、缓冲、压缩、可选限流与缓存、日志要求，并给出上线核对清单与参考片段。
>
> **仓库不提交可部署的 nginx 配置**，也不采用 Caddy。参考片段只是文档示例，必须按自己的 vhost 改写并用 `nginx -t` 校验。配置是否正确，最终由 staging/生产上的运行时观测（`GET /api/health/edge`）与本文核对清单证明，而不是由仓库里的文件证明。

---

## 1. 部署拓扑

```text
浏览器
  │  HTTPS（TLS 终止；HSTS 由接入层负责）
  ▼
平台 nginx（运维维护：TLS/HSTS、body 上限、路由、压缩、可选限流、访问日志）
  │  覆盖写 X-Forwarded-For / X-Forwarded-Proto；可透传/生成 X-Request-ID
  │
  ├── /api/*    → 127.0.0.1:8000（FastAPI）
  ├── /media/*  → 127.0.0.1:8000（FastAPI，关闭代理缓冲）
  └── /*        → 127.0.0.1:4321（Astro SSR：公共页 + /admin + /_astro/* 资产）
```

- **只有一层接入**。浏览器不直连应用进程，也不存在第二层边缘代理。
- 仓库**不包含** nginx 配置文件；`deploy/` 下没有 nginx.conf，也没有 Caddyfile。
- 3.0.0 **删除**了 Astro 业务代码里的代理（`pages/api/[...path].ts`、`pages/media/[...path].ts`、`lib/proxy.ts`）与 `BLOG_PROXY_SECRET`。Astro 只做前端框架与 SSR 运行体，不再转发 API/媒体。
- 两个应用进程只监听**回环/私有网络**，不得发布到公网。compose 只把端口发布到宿主机回环（`127.0.0.1:4321`、`127.0.0.1:8000`），由同机 nginx 反向代理。
- TLS 证书与 **HSTS 是 nginx 的职责**；应用不设置 HSTS 头。

---

## 2. 路由要求

| 前缀        | 上游             | 说明                                                       |
| ----------- | ---------------- | ---------------------------------------------------------- |
| `/api/`     | `127.0.0.1:8000` | FastAPI 全部接口（含 `/api/health`、`/api/health/edge`）   |
| `/media/`   | `127.0.0.1:8000` | FastAPI 媒体响应，需关闭代理缓冲（见第 4 节）              |
| 其余（`/`） | `127.0.0.1:4321` | Astro SSR：公共页、`/admin` 后台页面、`/_astro/*` 静态资产 |

- 只做**前缀转发**，不要在 nginx 里重写路径；应用内部路径以 `/api`、`/media` 为准。
- `/admin` 页面走 Astro（`:4321`），其数据请求走 `/api/`（`:8000`），两者都经同一入口；后端与 Astro 只监听内网/回环，nginx 是唯一对外监听者。
- `/api/bootstrap` 是公共页唯一的聚合读接口（无 cookie/会话依赖），应用已输出 `ETag` 与 `Cache-Control`（含 `s-maxage=60`）；接入层默认无需为它额外加缓存。
- 分页使用**路径式 URL**（如 `/tags/{tag}/page/{n}`）；旧 `?page=` 的 301 重定向由应用层（Astro）发出，nginx 不要改写或缓存这些 301。

---

## 3. 转发头与真实 IP

对 `/api/`、`/media/` 两条 `proxy_pass`（以及任何为它们新增的 location）都必须：

```nginx
proxy_set_header X-Forwarded-For   $remote_addr;   # 覆盖，不是追加
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Host              $host;
```

**严禁使用 `$proxy_add_x_forwarded_for`**：它会把客户端自带的 XFF 保留在列表里，而按约定最左值就是客户端可控的伪造值，真实 IP 会被绕过，限流与审计随之失效。

应用侧信任模型：

- 后端以 `uvicorn --proxy-headers --forwarded-allow-ips=${BLOG_TRUSTED_PROXY:-127.0.0.1}` 启动（见 `backend/Dockerfile` 与 `docker-compose.yml`）。
- uvicorn **只信任该 peer**（默认 `127.0.0.1`）提供的转发头；其他来源伪造的 `X-Forwarded-For` 被忽略。
- 若 nginx 不与应用同机，把 `BLOG_TRUSTED_PROXY` 设为 nginx 实际连接源地址（多个用逗号分隔），不要设为 `0.0.0.0/0` 之类的宽泛值；应用侧没有可泄露、可伪造的“真实 IP 密钥头”（`x-blog-proxy-secret` / `x-blog-real-ip` 已删除）。

---

## 4. 体积、超时与媒体缓冲

```nginx
client_max_body_size 210m;   # 必须 ≥ 210m
proxy_read_timeout   180s;   # 必须 ≥ 180s
```

- 应用默认的管理员单次上传硬上限是 `BLOG_ADMIN_MAX_UPLOAD_MB=200`（200 MiB）。`210m` 留出余量并让 nginx **更早**拒绝超大请求，避免流量进入应用进程；应用上调该上限时必须同步上调 nginx 的 `client_max_body_size`。
- `proxy_read_timeout 180s` 覆盖大图上传与媒体下载；不要低于该值。
- 若在 location 级覆盖这些值，确认 `/api/`、`/media/`、`/` 三者都不低于上述下限。
- **`/media/` 必须关闭代理缓冲**：`proxy_buffering off;`。否则大图/大文件会同时占用 nginx 与应用两层临时文件/内存，增加首字节延迟与磁盘压力；关闭后响应直接流式回传。

---

## 5. 压缩

- 只在**这一层**启用 gzip 或 brotli；应用侧不再另做压缩。按需配置 `gzip_types`，不要把已压缩格式重复压（图片通常不必再压）。验证“没有重复 Content-Encoding”（重复编码会破坏客户端解析）：

```bash
curl -sI -H 'Accept-Encoding: gzip' https://your.site/ | grep -i '^content-encoding'
```

期望：最多出现一行，值为 `gzip` 或 `br`；**不应**出现 `gzip, gzip` 之类重复值。

---

## 6. 可选加固：边缘限流

这是应用层限流之外的**额外一层防御，不是安全前提**。应用自身对登录（IP + 账号）、预览、上传的限流是必需的，nginx 限流不能替代它。

- `limit_req_zone` **必须声明在 `http {}` 层**，写进 `server {}` 会报错。
- 登录路径示例（可选）：

```nginx
# http {} 层
limit_req_zone $binary_remote_addr zone=blog_login:10m rate=10r/m;

# server {} 内
location = /api/auth/login {
    limit_req zone=blog_login burst=5 nodelay;
    proxy_pass http://127.0.0.1:8000;
    # ... 同样覆盖转发头（见第 3 节）
}
```

- 新增带 `limit_req` 的 location 时，**必须同样覆盖写转发头**，否则会出现“限流按错误 IP 分桶”或真实 IP 丢失。

---

## 7. 可选缓存

默认**不需要**代理缓存：应用已为页面与公开 API 输出 ETag / `Cache-Control`，代理层再加缓存只会增加失效复杂度。

若确实启用 `proxy_cache`，必须满足：

- 排除 `/api/admin/*`（后台数据一律不缓存）。
- 排除带 `Cookie` 请求头的请求（应在 `proxy_cache_key` / `map` 中体现，不能只靠默认行为）。
- 排除任何带 `Set-Cookie` 的响应（如 `proxy_no_cache $upstream_http_set_cookie`），否则会缓存登录态。
- 公共页与 `/api/bootstrap` 可复用应用已给出的 `ETag` / `Cache-Control`（`s-maxage=60`），但缓存键不得包含 `Cookie`；如需缓存 `/api/bootstrap`，同样受上面三条约束。
- 改动后检查：公开页/媒体按预期命中，`/api/admin/*` 不被缓存。

---

## 8. 日志与请求关联

- 保留 nginx 访问日志（含 `$request_id`、状态码、上游耗时）。
- 可选：生成并透传请求 ID，便于 nginx 与应用日志关联：`proxy_set_header X-Request-ID $request_id;`
- 应用侧兜底：请求缺少 `X-Request-ID` 时，FastAPI 会生成一个并在响应头回写；因此即使 nginx 不生成，贯通性也成立，nginx 生成时以 nginx 的值为准。
- 排查问题时用同一个 `X-Request-ID` 在两侧日志中 grep 即可串联一次请求。

---

## 9. 应用侧自检端点：`GET /api/health/edge`

只读端点，报告应用**实际观测到**的接入层状态（定义见 `backend/app/routes/health.py`）：

| 字段              | 含义                                                                                                                      |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `ok`              | 固定 `true`，表示端点可用                                                                                                 |
| `client_ip`       | 应用最终采信的客户端 IP（uvicorn 受信代理改写后的 `request.client`），限流与审计使用它                                    |
| `forwarded_for`   | 应用收到的原始 `X-Forwarded-For` 头，用于确认接入层是“覆盖”而非“追加”                                                     |
| `forwarded_proto` | 应用收到的 `X-Forwarded-Proto`，用于确认 HTTPS 语义                                                                       |
| `request_id`      | 本次请求的关联 ID（nginx 生成或应用兜底生成）                                                                             |
| `trusted_proxy`   | 当前 `BLOG_TRUSTED_PROXY` 配置值（只信任该 peer 的转发头）                                                                |
| `cookie_secure`   | 会话 Cookie 是否带 `Secure`（由 `BLOG_SITE_URL`/`BLOG_FRONTEND_URL` 的 https 推导，也可由 `BLOG_COOKIE_SECURE` 显式设置） |

用法：在 staging/生产上**经真实入口**请求它，逐条对照第 11 节核对清单：

```bash
curl -s https://your.site/api/health/edge
```

---

## 10. 本地开发不涉及 nginx

- 本地不安装、不运行 nginx；浏览器保持**同源** `http://127.0.0.1:4321`。
- `/api`、`/media` 由 Astro/Vite 的**仅 dev 生效**的 `vite.server.proxy` 转发到 `BLOG_API_INTERNAL_URL`（默认 `http://127.0.0.1:8000`），并设置 `xfwd: false`，即不把客户端伪造的转发头传给后端。
- 生产与开发的路由差异只有“谁做路由”：生产是 nginx，开发是 Vite proxy。因此本地不验证第 11 节的边缘核对项，接入层行为统一在 staging/CI 按本文核对清单验证（见 `docs/archive/3.0.0/REFACTOR-3.0.0.md` 6.2 的边缘测试行）。

---

## 11. 上线核对清单

逐条执行并记录结果；全部通过才算接入层就绪。命令中的 `https://your.site` 换成真实域名。

1. **路由正确**：`curl -sI https://your.site/api/health` 返回 200 且来自 FastAPI；`curl -sI https://your.site/` 返回 200 且 `Content-Type: text/html`（Astro 页面）；`/admin` 返回后台页面而非 404。
2. **伪造 XFF 无效**：`curl -s -H 'X-Forwarded-For: 203.0.113.9' https://your.site/api/health/edge`。期望 `forwarded_for` 等于**真实客户端 IP**（不是 `203.0.113.9`），且 `client_ip` 也等于真实 IP。若返回伪造地址，说明用了“追加”语义，必须改为覆盖。
3. **协议被观测为 HTTPS**：同一次响应中 `forwarded_proto` 为 `https`；若为 `http`，检查该 location 是否漏了 `X-Forwarded-Proto $scheme`。
4. **413 来自 nginx**：生成超过 210m 的请求体后上传（例如 `curl -s -o /dev/null -w '%{http_code}\n' -X POST --data-binary @/tmp/big.bin https://your.site/api/health`），期望 `413`，且响应由 nginx 产生（nginx 413 页面或 `Server: nginx`），不是应用返回的 JSON 错误体。这证明 body 上限在入口就生效。
5. **`/media/` 未缓冲**：对较大的现有媒体文件取首字节耗时（`curl -o /dev/null -w '%{time_starttransfer}\n' https://your.site/media/<file>`），确认首字节早早到达；并核对 vhost 中 `/media/` 确有 `proxy_buffering off`。
6. **Cookie 带 Secure**：用真实账号登录，检查响应 `Set-Cookie` 含 `Secure`（`curl -si -c /tmp/c.txt -X POST https://your.site/api/auth/login -H 'Content-Type: application/json' -d '{"username":"...","password":"..."}' | grep -i '^set-cookie'`）。前提是 `BLOG_SITE_URL` 为 https；同时 `/api/health/edge` 的 `cookie_secure` 应为 `true`。
7. **X-Request-ID 贯通**：`curl -si -H 'X-Request-ID: edge-check-001' https://your.site/api/health/edge`，期望响应头 `X-Request-ID: edge-check-001` 且 JSON 中 `request_id` 相同；不带该头再请求一次，应仍返回一个非空 `X-Request-ID`（应用兜底生成）。
8. **压缩不重复**：`curl -sI -H 'Accept-Encoding: gzip' https://your.site/ | grep -i '^content-encoding'`，最多一行且无重复编码（见第 5 节）。
9. **HSTS 存在**：`curl -sI https://your.site/ | grep -i strict-transport-security` 应看到 nginx 配置的 HSTS 头。
10. **限流（如启用）**：连续请求登录路径超过阈值，观察到 nginx 返回 429；同时确认应用层限流仍独立生效（不依赖 nginx）。未启用边缘限流时，本条记为“未启用”，但要确认应用层登录/上传限流的 429 与 `Retry-After` 仍在。
11. **缓存（如启用）**：确认 `/api/admin/*`、带 Cookie 请求、带 `Set-Cookie` 响应均不被缓存；未启用时本条记为“未启用”。

> 提醒：第 2、3、6、7 条都能通过 `/api/health/edge` 在应用侧观测，不依赖查看 nginx 配置文件。这也是“仓库不提交 nginx 配置”的补偿手段。

---

## 12. 参考片段（仅供文档示例，不是仓库可部署配置）

> **`仅供文档示例，不是仓库可部署配置`。运维需按自己 vhost 改写，并在 reload 前用 `nginx -t` 校验。**仓库不提交、不校验该片段。

```nginx
# http {} 层（与其它站点共用时放在 http {} 内；不能写进 server {}）
limit_req_zone $binary_remote_addr zone=blog_login:10m rate=10r/m;

server {
    listen 443 ssl;
    server_name your.site;
    ssl_certificate     /path/to/site.pem;
    ssl_certificate_key /path/to/site.key;

    # TLS/HSTS 由接入层负责，应用不设置 HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    client_max_body_size 210m;
    proxy_read_timeout   180s;
    proxy_http_version   1.1;
    proxy_set_header     Connection "";

    # 可选：让 nginx 生成请求 ID，应用会沿用并回写
    proxy_set_header X-Request-ID $request_id;

    # 压缩只在这一层启用
    gzip on;
    gzip_types text/html text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;

    access_log /var/log/nginx/your.site.access.log;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;   # 覆盖，不追加
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 可选加固：登录限流；新增 location 必须同样覆盖转发头
    location = /api/auth/login {
        limit_req zone=blog_login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_buffering off;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:4321;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

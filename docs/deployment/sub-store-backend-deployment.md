# Sub-Store 后端安装与订阅转换部署记录

> 最后核对日期：2026-06-06  
> 用途：供后续维护者或其他 AI 复现、排错和继续改造  
> 仓库提交：`9ecf9d6aa3f3aa39da7e75aa9e469adb636b1d7d`  
> Sub-Store 版本：`2.24.7`

## 0. 参考仓库与文档

后续 AI 或维护者应优先参考以下仓库的实际源码、Release 和文档，不要只依赖本部署记录。

### 当前使用的服务仓库

```text
https://github.com/hdgcoding/Sub-Store
```

对应部署提交：

```text
https://github.com/hdgcoding/Sub-Store/commit/9ecf9d6aa3f3aa39da7e75aa9e469adb636b1d7d
```

### Sub-Store 官方仓库

```text
https://github.com/sub-store-org/Sub-Store
https://github.com/sub-store-org/Sub-Store/wiki
https://github.com/sub-store-org/Sub-Store/releases
```

官方前端仓库。本次部署没有安装前端，但后续需要 Web 管理界面时可参考：

```text
https://github.com/sub-store-org/Sub-Store-Front-End
```

### 规则仓库

```text
https://github.com/Loyalsoldier/clash-rules
```

规则地址格式：

```text
https://raw.githubusercontent.com/Loyalsoldier/clash-rules/release/<RULE>.txt
https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/<RULE>.txt
```

### Mihomo 仓库

```text
https://github.com/MetaCubeX/mihomo
https://wiki.metacubex.one
https://github.com/MetaCubeX/mihomo/releases
```

### 客户端仓库

```text
https://github.com/clash-verge-rev/clash-verge-rev
```

Shadowrocket 是闭源客户端，没有可用于核对实现的官方开源仓库。

## 1. 最终目标

在服务器上部署纯 Sub-Store 后端，并提供一个交互命令：

```bash
sub-store-convert
```

交互命令支持：

- 菜单式操作：新增、查看、修改、删除订阅。
- 输入远程订阅 URL、本地文件路径或单个节点链接。
- 输出 Clash Verge、Clash Meta/Mihomo、Shadowrocket 等格式。
- 为 Mihomo 生成完整配置：
  - `proxies`
  - `proxy-groups`
  - `rule-providers`
  - `rules`
- 使用 [Loyalsoldier/clash-rules](https://github.com/Loyalsoldier/clash-rules) 在线规则。
- 选择白名单、黑名单或自定义规则策略。
- 将结果发布成客户端可直接导入的订阅 URL。
- 使用同一个发布名称重新生成时，更新原订阅内容并保持 URL 不变。

本次部署不包含 Web 前端。Sub-Store 后端直接监听 `0.0.0.0:3000`，客户端通过 `http://<SERVER_IP>:3000/<PREFIX>/share/file/<NAME>` 访问订阅。

## 2. 部署信息

以下值在每次部署时由用户提供或自动生成：

| 项目 | 占位符 | 说明 |
| --- | --- | --- |
| 服务器 IP | `<SERVER_IP>` | 用户服务器公网 IP |
| SSH 用户 | `root` | SSH 登录用户 |
| SSH 密钥 | `<SSH_KEY_PATH>` | 用户本地私钥路径 |
| 系统 | Alibaba Cloud Linux 3 / Debian 等 | 具体版本以实际为准 |
| API 前缀 | `<PREFIX>` | `openssl rand -hex 16` 生成 |
| Node.js | `v20.x` | 来自 NodeSource 或系统仓库 |
| 后端监听 | `0.0.0.0:3000` | 直接对外暴露 |
| 程序 | `/opt/sub-store/sub-store.bundle.js` | 固定路径 |
| 数据目录 | `/var/lib/sub-store` | 固定路径 |
| 环境文件 | `/etc/sub-store.env` | 固定路径 |
| systemd 服务 | `sub-store.service` | 固定名称 |
| 交互命令 | `/usr/local/bin/sub-store-convert` | 固定路径 |
| Swap | 2GB，swappiness=10 | 推荐配置 |

### 访问地址

后端基地址：

```text
http://<SERVER_IP>:3000/<PREFIX>
```

示例订阅地址：

```text
http://<SERVER_IP>:3000/<PREFIX>/share/file/clash-verge
```

### 安全说明

- API 前缀只是降低被扫描发现的概率，不是身份认证。
- 使用 HTTP，订阅内容和节点信息在传输途中没有 TLS 保护。
- 生产环境应使用 Nginx 反向代理 + HTTPS、访问控制或防火墙白名单。
- 不要把 SSH 私钥内容写入仓库。部署时只传入私钥路径。
- 如果这份文档公开，应先更换 API 前缀。
- 防火墙/安全组需要放行 3000 端口。

## 3. 已确认的仓库能力

Sub-Store 的直接转换接口：

```text
POST /api/proxy/parse
```

请求体：

```json
{
  "data": "订阅内容或节点内容",
  "client": "mihomo"
}
```

主要输出目标包括：

- `mihomo`
- `sing-box`
- `Surge`
- `Loon`
- `QX`
- `Shadowrocket`
- `Stash`
- `V2Ray`
- `URI`
- `JSON`

文件托管接口：

```text
POST    /api/files
PATCH   /api/file/:name
GET     /api/wholeFile/:name
DELETE  /api/file/:name
GET     /api/files
GET     /share/file/:name
```

注意：

- `/api/file/:name` 的 GET 返回文件正文。
- 查询文件元数据和判断文件是否存在应使用 `/api/wholeFile/:name`。
- 列出所有已发布文件使用 `GET /api/files`。

## 4. 本地构建和测试

进入后端目录：

```bash
cd backend
```

安装锁定版本依赖：

```bash
npx -y pnpm@11.0.9 install --frozen-lockfile
```

运行测试：

```bash
npx -y pnpm@11.0.9 test
```

本次结果：

```text
567 passing
```

构建 Node 单文件产物：

```bash
npx -y pnpm@11.0.9 bundle:esbuild
```

产物：

```text
backend/dist/sub-store.bundle.js
```

本次产物 SHA-256：

```text
5b4822cd87ea2115dbdafbfb4d8bd485c9ffd31bc93d3508dc6a0a805484a6c4
```

构建时出现 esbuild `direct eval` 警告属于仓库现有实现；构建成功且全部测试通过后继续部署。

## 5. SSH 连接

连接：

```bash
ssh -i <SSH_KEY_PATH> -p 22 root@<SERVER_IP>
```

如果私钥权限过宽，OpenSSH 会拒绝：

```bash
install -m 600 <SSH_KEY_PATH> /tmp/deploy-key
ssh -i /tmp/deploy-key -p 22 root@<SERVER_IP>
```

## 6. 服务器环境检查

建议部署前检查：

```bash
uname -srm
cat /etc/os-release
command -v node || true
command -v systemctl
ss -lntp
df -h /
free -h
```

本次发现：

- Node.js 未安装。
- systemd 可用。
- `3000` 未占用。

## 7. 安装 Node.js 和运行用户

服务器执行（NodeSource 方式，适用于 RHEL/CentOS/Alma/Alinux）：

```bash
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
yum install -y nodejs
```

Debian/Ubuntu 方式：

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  nodejs ca-certificates
```

创建低权限用户和目录：

```bash
getent passwd substore >/dev/null || useradd --system \
  --home-dir /var/lib/sub-store \
  --shell /usr/sbin/nologin \
  substore

install -d -o root -g root -m 0755 /opt/sub-store
install -d -o substore -g substore -m 0750 /var/lib/sub-store
```

## 8. 上传构建产物

本地执行：

```bash
scp -i <SSH_KEY_PATH> -P 22 \
  backend/dist/sub-store.bundle.js \
  root@<SERVER_IP>:/opt/sub-store/sub-store.bundle.js
```

服务器设置权限：

```bash
chown root:root /opt/sub-store/sub-store.bundle.js
chmod 0644 /opt/sub-store/sub-store.bundle.js
```

验证哈希：

```bash
sha256sum /opt/sub-store/sub-store.bundle.js
```

## 9. 后端环境配置

生成随机 API 前缀：

```bash
openssl rand -hex 16
```

创建 `/etc/sub-store.env`：

```dotenv
NODE_ENV=production
SUB_STORE_BACKEND_API_HOST=0.0.0.0
SUB_STORE_BACKEND_API_PORT=3000
SUB_STORE_BACKEND_PREFIX=1
SUB_STORE_FRONTEND_BACKEND_PATH=/<PREFIX>
SUB_STORE_DATA_BASE_PATH=/var/lib/sub-store
SUB_STORE_CORS_ALLOWED_ORIGINS=
```

权限：

```bash
chown root:root /etc/sub-store.env
chmod 0600 /etc/sub-store.env
```

关键点：

- 设置 `SUB_STORE_BACKEND_PREFIX` 后，必须同时设置以 `/` 开头的 `SUB_STORE_FRONTEND_BACKEND_PATH`。
- 不带随机前缀的 `/api`、`/download` 和 `/share` 路径应返回 `404`。
- 数据必须写入独立目录，不能依赖程序当前目录。
- `SUB_STORE_CORS_ALLOWED_ORIGINS=` 在当前实现中最终仍显示 Node 默认 `*`。
- 默认 JSON 请求体上限是 `1mb`。除非有明确需求，不要长期提高。

## 10. systemd 服务

创建 `/etc/systemd/system/sub-store.service`：

```ini
[Unit]
Description=Sub-Store subscription conversion backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=substore
Group=substore
WorkingDirectory=/var/lib/sub-store
EnvironmentFile=/etc/sub-store.env
ExecStart=/usr/bin/node /opt/sub-store/sub-store.bundle.js
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/sub-store
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=600M

[Install]
WantedBy=multi-user.target
```

启用：

```bash
systemctl daemon-reload
systemctl enable --now sub-store
```

检查：

```bash
systemctl is-enabled sub-store
systemctl is-active sub-store
systemctl status sub-store --no-pager
journalctl -u sub-store -n 100 --no-pager
```

预期：

```text
enabled
active
```

## 11. 基础 API 验证

环境接口：

```bash
curl -fsS \
  http://127.0.0.1:3000/<PREFIX>/api/utils/env
```

确认未加前缀时不可访问：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:3000/api/utils/env
```

预期：

```text
404
```

测试节点转换：

```bash
curl -fsS \
  -H 'Content-Type: application/json' \
  --data '{
    "data":"ss://YWVzLTEyOC1nY206cGFzcw@127.0.0.1:8388#test",
    "client":"mihomo"
  }' \
  http://127.0.0.1:3000/<PREFIX>/api/proxy/parse
```

公网验证：

```bash
curl -fsS \
  http://<SERVER_IP>:3000/<PREFIX>/api/utils/env
```

## 12. Swap 配置

服务器约 2GB 内存，配置 2GB swap 作为补充：

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

echo '/swapfile none swap sw 0 0' >> /etc/fstab

sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf

sysctl vm.vfs_cache_pressure=50
echo 'vm.vfs_cache_pressure=50' >> /etc/sysctl.conf
```

## 13. 交互转换脚本

脚本源码已抽离为独立文件：

```text
docs/deployment/sub-store-convert.sh
```

安装方式：修改脚本头部的 `<PREFIX>` 和 `<SERVER_IP>` 为实际部署值，然后上传到服务器：

```bash
scp -i <SSH_KEY_PATH> docs/deployment/sub-store-convert.sh \
  root@<SERVER_IP>:/usr/local/bin/sub-store-convert
chmod 0755 /usr/local/bin/sub-store-convert
```

脚本中的以下值必须与实际部署一致：

```bash
API='http://127.0.0.1:3000/<PREFIX>/api/proxy/parse'
FILE_API='http://127.0.0.1:3000/<PREFIX>/api'
PREFIX='<PREFIX>'
SERVER_IP='<SERVER_IP>'
```

脚本支持三种模式：

- **快照模式**：一次性转换并发布为托管文件（`/share/file`），上游更新后需手动重新生成。
- **实时模式**：管理上游订阅（`/api/subs`），客户端通过 `/download` 链接拉取，后端实时拉取上游并转换。
- **定时任务**：创建 artifact 定时任务（`/api/artifacts`），按 cron 定时拉取上游刷新缓存，无需配置 Gist（`upload: false`，仅刷新缓存和记录执行时间）。

### 13.1 菜单结构

脚本启动后显示主菜单：

```text
Sub-Store 订阅管理

  快照模式（托管文件，上游更新后需手动重新生成）
    1. 新增订阅（转换并发布）
    2. 查看已发布订阅
    3. 修改订阅（重新转换并覆盖）
    4. 删除订阅
  实时模式（上游订阅，客户端拉取时实时转换）
    5. 添加/更新上游订阅
    6. 查看上游订阅及链接
    7. 删除上游订阅
  定时任务（按 cron 拉取上游刷新缓存）
    8. 创建/更新定时任务
    9. 查看定时任务
   10. 手动触发同步
   11. 删除定时任务
    0. 退出
```

- **快照模式 1-4**：一次性转换并发布为静态托管文件。
- **实时模式 5-7**：录入/查看/删除上游订阅。添加同名订阅即更新。上游结果默认缓存 1 小时（`DEFAULT_CACHE_TTL`），添加时可选择每次请求都实时拉取上游（订阅设置 `noCache: true`）。
- **定时任务 8-11**：为某个上游订阅创建 artifact（`sync: true`、`upload: false`、`cron`），后端按 cron 拉取上游刷新缓存，客户端 `/download` 即可始终拿到较新数据。任务立即同步一次可验证上游可访问性。
- **退出**：退出脚本。

### 13.2 发布输出

发布成功后输出访问地址：

```text
订阅链接：
  http://<SERVER_IP>:3000/<PREFIX>/share/file/<NAME>
```

### 13.3 删除操作

删除时显示编号列表：

```text
已发布的订阅：

  1. clash-verge
  2. shadowrocket

  0. 取消

请选择要删除的序号 [0]:
```

选择后二次确认：

```text
确认删除: clash-verge (y/N)
```

### 13.4 脚本源代码

脚本完整源码见仓库文件 `docs/deployment/sub-store-convert.sh`，此处不再内联，避免两处维护不一致。

脚本实现要点（与后端接口对应）：

- 快照模式：`POST /api/proxy/parse` 转换，`POST /api/files` / `PATCH /api/file/:name` 发布，`DELETE /api/file/:name` 删除。
- 实时模式：`POST /api/subs` / `PATCH /api/sub/:name`（同名即更新），`DELETE /api/sub/:name` 删除。
- 定时任务：`POST /api/artifacts` / `PATCH /api/artifact/:name`，字段 `sync: true`、`source: <订阅名>`、`platform: <目标格式>`、`upload: false`、`cron`。手动同步使用 `GET /api/sync/artifact/:name`（单个）或 `GET /api/sync/artifacts`（全部）。
- cron 调度要求 artifact 同时具有 `sync` 和 `source` 字段（见 `backend/src/utils/artifact-cron.js`）；未配置 Gist 凭据时，`upload: false` 的任务仍会按期执行，仅刷新缓存并更新执行时间（见 `backend/src/restful/sync.js` 的 `syncArtifactItem`）。

## 14. 客户端差异

### Clash Verge 和 Clash Meta/Mihomo

可导入完整 Mihomo YAML，包括节点、策略组和远程规则。

"转换好的 link"本质是：

```text
GET /share/file/:name
```

它返回完整 YAML，不是单个 `vmess://`、`vless://` 或 `ss://` URI。

### Shadowrocket

Shadowrocket 不直接使用 Mihomo 的 `rule-providers` 完整配置结构。

脚本对 Shadowrocket 只生成 Shadowrocket 兼容节点输出，并可将结果发布成订阅 URL。不要把 Mihomo YAML 强行作为 Shadowrocket 规则配置。

## 15. Loyalsoldier 规则策略

白名单模式默认包含：

- `applications` -> `DIRECT`
- `private` -> `DIRECT`
- `reject` -> `REJECT`
- `icloud` -> `DIRECT`
- `apple` -> `DIRECT`
- `google` -> `PROXY`
- `proxy` -> `PROXY`
- `direct` -> `DIRECT`
- `lancidr` -> `DIRECT`
- `cncidr` -> `DIRECT`
- `telegramcidr` -> `PROXY`
- 最终 `MATCH` -> `PROXY`

黑名单模式默认包含：

- `applications`
- `private`
- `reject`
- `tld-not-cn`
- `gfw`
- `telegramcidr`
- 最终 `MATCH` -> `DIRECT`

自定义模式允许逐个选择规则集，并指定：

- `PROXY`
- `DIRECT`
- `REJECT`

## 16. 规则下载实测

在国内服务器上实测：

| 规则源 | 结果 |
| --- | --- |
| GitHub Raw 直连 | 完全不通（`raw.githubusercontent.com` 连接超时） |
| jsDelivr 直连 | 极慢（direct.txt 60秒只下了 875KB/2.34MB，约 14KB/s） |

因此：

- **选项1（GitHub Raw 经 PROXY）** — 规则由客户端 Mihomo 通过代理节点下载，服务器不涉及，**推荐**。
- **选项2（jsDelivr 经 PROXY）** — 同上，客户端通过代理下载。
- **选项3（jsDelivr 直连）** — 不推荐，客户端直连 jsDelivr 极慢。

Mihomo 支持在 `rule-providers` 中设置 `proxy: PROXY`，让规则通过已可用的代理节点下载：

```yaml
rule-providers:
  direct:
    type: http
    behavior: domain
    url: "https://raw.githubusercontent.com/Loyalsoldier/clash-rules/release/direct.txt"
    path: ./ruleset/direct.yaml
    interval: 86400
    proxy: PROXY
```

首次切换仍需下载规则；后续由 Mihomo 本地缓存，通常会更快。

### 为什么删除 GEOIP

配置已有 `lancidr` 和 `cncidr` 规则集，再追加：

```yaml
- GEOIP,LAN,DIRECT
- GEOIP,CN,DIRECT
```

会产生重复匹配，并可能触发额外 MMDB 下载。最终脚本不再生成这两条 `GEOIP`。

## 17. 其他问题及解决

### 17.1 `/api/file/:name` 不能用于存在性检查

问题：GET 返回文件正文，脚本按 JSON 解析失败。

解决：改用：

```text
GET /api/wholeFile/:name
```

### 17.2 不存在文件返回 HTTP 500

部分不存在文件响应不是 HTTP 404，而是 HTTP 500，正文中包含：

```json
{
  "error": {
    "code": "FILE_NOT_FOUND"
  }
}
```

交互脚本同时检查 HTTP 状态和正文错误码，把该情况视为"文件不存在"，随后调用 `POST /api/files`。

### 17.3 完整配置被误解为节点链接

完整 Mihomo 配置包含节点、策略组和规则，不能表示为单个代理 URI。

解决：通过 Sub-Store 文件接口发布 YAML，并返回可导入的 HTTP 订阅 URL。

### 17.4 同名发布

首次发布：

```text
POST /api/files
```

再次使用相同名称：

```text
PATCH /api/file/:name
```

客户端订阅 URL 保持不变。

### 17.5 规则同步时 HTTP 413

`direct.txt` 超过 Sub-Store 默认 `1mb` JSON 限制，上传时返回 HTTP 413。当前方案使用在线规则，不经过服务器中转，不存在此问题。

### 17.6 删除文件接口

删除已发布订阅使用：

```text
DELETE /api/file/:name
```

### 17.7 脚本写入注意事项

通过 SSH heredoc 写入脚本时，特殊字符（`$`、反引号、反斜杠等）会被本地 shell 解析，导致脚本损坏。推荐做法：先在本地写好文件，再 `scp` 上传到服务器。

## 18. 日常使用

登录服务器：

```bash
ssh -i <SSH_KEY_PATH> root@<SERVER_IP>
```

运行：

```bash
sub-store-convert
```

推荐 Clash Verge 选择：

```text
菜单：1. 新增订阅（转换并发布）
客户端：Clash Verge / Clash Meta / Mihomo
输出模式：完整 Mihomo 配置
规则策略：白名单
规则下载源：GitHub Raw，经 PROXY 下载
交付方式：发布为订阅 URL
订阅名称：clash-verge
```

重新生成同名 `clash-verge` 后，在客户端刷新原订阅即可。

### 18.1 实时模式推荐用法（上游不定期更新节点时）

```text
菜单：5. 添加/更新上游订阅
订阅名称：my-airport
上游订阅 URL：<机场订阅 URL>
User-Agent：clash.meta
每次请求都实时拉取上游：N（默认，配合定时任务刷新缓存）
```

客户端使用输出给出的 `/download` 链接（拉取时实时转换），上游更新后客户端刷新订阅即可拿到新节点，URL 永不变化。

再创建定时任务保持缓存新鲜：

```text
菜单：8. 创建/更新定时任务
选择订阅：my-airport
任务名称：auto-my-airport
输出格式：ClashMeta
cron：0 * * * *（每小时）
立即执行一次同步：Y
```

说明：

- 上游结果默认缓存 1 小时，定时任务按 cron 拉取上游刷新缓存。
- `/download` 的 ClashMeta 输出只含 `proxies` 节点；完整规则（策略组/rule-providers）在 Clash Verge 中用"全局扩展配置（Merge）"补充，或继续使用快照模式 1 的完整配置托管。
- 无 Gist 凭据时定时任务照常执行（仅刷新缓存并更新执行时间），日志中体现为 `[ARTIFACT CRON]`（`journalctl -u sub-store`）。

## 19. 运维命令

查看状态：

```bash
systemctl status sub-store --no-pager
```

查看日志：

```bash
journalctl -u sub-store -f
```

重启：

```bash
systemctl restart sub-store
```

查看监听：

```bash
ss -lntp | grep ':3000'
```

检查数据：

```bash
ls -lah /var/lib/sub-store
```

当前数据主要保存在：

```text
/var/lib/sub-store/sub-store.json
/var/lib/sub-store/root.json
```

备份：

```bash
tar -C /var/lib -czf /root/sub-store-data-backup.tar.gz sub-store
```

恢复前应先停服务：

```bash
systemctl stop sub-store
tar -C /var/lib -xzf /root/sub-store-data-backup.tar.gz
chown -R substore:substore /var/lib/sub-store
systemctl start sub-store
```

查看已发布订阅：

```bash
sub-store-convert
# 选择 2. 查看已发布订阅
```

## 20. 升级流程

1. 在本地仓库拉取或切换目标提交。
2. 运行全部测试。
3. 构建 `backend/dist/sub-store.bundle.js`。
4. 记录新 SHA-256。
5. 备份服务器数据和旧程序。
6. 上传新产物。
7. 重启 systemd。
8. 验证环境接口、转换接口和现有订阅。

示例：

```bash
cd backend
npx -y pnpm@11.0.9 install --frozen-lockfile
npx -y pnpm@11.0.9 test
npx -y pnpm@11.0.9 bundle:esbuild
sha256sum dist/sub-store.bundle.js
```

服务器备份旧程序：

```bash
cp /opt/sub-store/sub-store.bundle.js \
  /opt/sub-store/sub-store.bundle.js.bak
```

上传并重启：

```bash
scp dist/sub-store.bundle.js root@<SERVER_IP>:/opt/sub-store/
ssh root@<SERVER_IP> 'systemctl restart sub-store'
```

## 21. 卸载

```bash
systemctl disable --now sub-store
rm -f /etc/systemd/system/sub-store.service
systemctl daemon-reload
rm -f /etc/sub-store.env
rm -f /usr/local/bin/sub-store-convert
rm -rf /opt/sub-store
```

数据目录单独处理：

```bash
rm -rf /var/lib/sub-store
userdel substore
```

删除数据前必须确认不再需要现有订阅和配置。

## 22. 最终验收清单

- [ ] 仓库测试 `567 passing`
- [ ] 构建产物生成，SHA-256 与部署一致
- [ ] Node.js 20 安装
- [ ] 低权限 `substore` 用户运行
- [ ] systemd 开机启动
- [ ] 随机 API 前缀生效
- [ ] 无前缀 API 返回 404
- [ ] 公网 `http://<SERVER_IP>:3000/<PREFIX>/api/utils/env` 可访问
- [ ] Mihomo 节点转换成功
- [ ] Clash Verge 完整配置生成成功
- [ ] Shadowrocket 订阅 URL 生成成功
- [ ] 同名订阅更新成功
- [ ] 菜单式操作：新增、查看、修改、删除
- [ ] 删除操作使用序号选择 + 二次确认
- [ ] Swap 2GB 配置完成
- [ ] 在线规则通过 `PROXY` 下载
- [ ] 重复 GEOIP 和额外 MMDB 初始化已移除
- [ ] 后端服务最终状态为 `active`

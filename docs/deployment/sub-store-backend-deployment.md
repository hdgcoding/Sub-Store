# Sub-Store 后端安装与订阅转换部署记录

> 最后核对日期：2026-09-02  
> 用途：供后续维护者或其他 AI 复现、排错和继续改造  
> 首次部署基于仓库提交：`9ecf9d6aa3f3aa39da7e75aa9e469adb636b1d7d`（Sub-Store 版本 `2.24.7`）

## 当前状态速览（AI / 新维护者先读这里）

> 本文档主体是按时间顺序沉淀的部署记录（第 4-17 节为首次部署的历史操作步骤），**当前实际状态以下表和 2.1、18.1 节为准**。执行变更前先对照本节确认，不要盲目按历史章节重做。

| 项 | 当前状态 |
| --- | --- |
| 服务器 | 阿里云 `47.116.182.13`（Alibaba Cloud Linux 3，Node v20.20.2），SSH 信息见 2.1 |
| 后端 | systemd 服务 `sub-store`，监听 `0.0.0.0:3000`，数据目录 `/var/lib/sub-store` |
| 对外入口 | nginx 443 反代 → `https://sub.minor.link/<PREFIX>/...`（3000 端口未对公网放行，**这是刻意配置**） |
| 使用模式 | 仅快照模式：`/share/file/<NAME>` 输出完整白名单 Mihomo 配置 |
| 节点保鲜 | crontab `23 * * * *` 运行 `/usr/local/bin/sub-store-refresh`（配置 `/etc/sub-store-refresh.json`），同名覆盖发布，订阅 URL 永不变化 |
| 交互脚本 | `/usr/local/bin/sub-store-convert`（快照模式菜单 1-4），源码在仓库 `docs/deployment/sub-store-convert.sh` |
| 已发布订阅 | JMS（已纳入自动刷新）、US-COMPANY（上游 URL 待补，未纳入自动刷新） |
| 已明确废弃 | 实时模式（`/download`、`/api/subs`、原生 artifact 定时任务）——只能输出节点列表、无法生成完整配置，2026-09-02 移除 |

常见任务 → 章节直达：

| 任务 | 章节 |
| --- | --- |
| 新增/更换上游订阅并纳入自动刷新 | 18.1 |
| 手动立即刷新 / 看刷新日志 | 18.1 手动操作 |
| 发布一个新订阅（首次） | 13 菜单 1，然后 18.1 纳入刷新 |
| 更换 API 前缀 | 9（env）+ 13（脚本头部）+ 18.1（刷新配置），改完 `systemctl restart sub-store` |
| 升级后端版本 | 20 |
| 排错 | 19（运维命令）+ 17（历史踩坑） |
| 从零重装 / 换机 | 4 → 7 → 8 → 9 → 10 → 13 → 18.1 → 22 |

注意事项：

- 改完仓库里的 `sub-store-convert.sh` 后**必须重新 scp 到服务器**，服务器上的脚本不会自动更新（见 13 节）。
- 全文占位符 `<PREFIX>` / `<SERVER_IP>` / `<PUBLIC_BASE>` 的实际值见 2.1。

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

在服务器上部署纯 Sub-Store 后端（无 Web 前端），配合两个自研命令：

- `sub-store-convert`：交互式管理快照订阅（转换 → 发布 → `/share/file/<NAME>` 订阅 URL）。
- `sub-store-refresh`：crontab 定时拉取上游订阅，重新生成为完整白名单 Mihomo 配置并同名覆盖。节点自动保鲜，订阅 URL 永不变化，客户端导入一次后无需任何操作。

生成的完整配置包含：`proxies`、`proxy-groups`、`rule-providers`、`rules`，使用 [Loyalsoldier/clash-rules](https://github.com/Loyalsoldier/clash-rules) 在线规则，支持白名单/黑名单策略。

对外访问统一走 `https://sub.minor.link/<PREFIX>/share/file/<NAME>`（nginx 反代，详见 2.1）。曾实现的实时 `/download` 模式已评估并放弃，原因与过程见 13 节开头及 18.1 历史说明。

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
| 后端监听 | `0.0.0.0:3000` | 仅限本机与 nginx 反代，公网经 `https://sub.minor.link`（见 2.1） |
| 程序 | `/opt/sub-store/sub-store.bundle.js` | 固定路径 |
| 数据目录 | `/var/lib/sub-store` | 固定路径 |
| 环境文件 | `/etc/sub-store.env` | 固定路径 |
| systemd 服务 | `sub-store.service` | 固定名称 |
| 交互命令 | `/usr/local/bin/sub-store-convert` | 固定路径 |
| Swap | 2GB，swappiness=10 | 推荐配置 |

### 2.1 当前实际部署值（2026-09-02 记录）

维护时可按此直连，以下值与上文占位符一一对应：

| 项目 | 实际值 |
| --- | --- |
| 服务器 IP | `47.116.182.13` |
| SSH 用户 | `root` |
| SSH 私钥路径 | `/Users/doghan/data/cloud/document/SSH_KEY/ALIYUN/aliyun_hdg` |
| 系统 | Alibaba Cloud Linux 3.2104 U13.1 (OpenAnolis Edition) |
| API 前缀 | `15abd9705c625da20ba80f1aafc2a1a6` |
| Node.js | `v20.20.2` |
| 公网入口（推荐） | `https://sub.minor.link/<PREFIX>`（nginx 443 反代） |
| 其他公网入口 | `https://minor.link/<PREFIX>`、`http://47.116.182.13:9090/<PREFIX>` |

标准登录命令：

```bash
ssh -i /Users/doghan/data/cloud/document/SSH_KEY/ALIYUN/aliyun_hdg root@47.116.182.13
```

当前实际架构与第 2 节描述的差异：

- 后端进程监听 `0.0.0.0:3000`，但阿里云安全组**未放行 3000**，公网无法直连。
- 实际由 nginx（`/etc/nginx/conf.d/sub.minor.link.conf` 等）在 80/443/9090 反代 `/<PREFIX>/` 到 `http://127.0.0.1:3000`，外部一律走 `https://sub.minor.link/<PREFIX>/...`。
- 客户端订阅链接、脚本输出的对外链接均应使用域名（脚本头部 `PUBLIC_BASE`），`127.0.0.1:3000` 仅限服务器本机（脚本内 `API`/`FILE_API`）。

注意：API 前缀随本仓库公开，泄露风险见下方"安全说明"；若文档外泄应更换前缀（改 `/etc/sub-store.env` 后 `systemctl restart sub-store`，并同步更新脚本头部值）。

### 访问地址

后端基地址（公网，nginx 反代，客户端一律用这个）：

```text
https://sub.minor.link/<PREFIX>
```

示例订阅地址：

```text
https://sub.minor.link/<PREFIX>/share/file/clash-verge
```

服务器本机调试地址（仅限 SSH 进服务器后使用）：

```text
http://127.0.0.1:3000/<PREFIX>
```

### 安全说明

- API 前缀只是降低被扫描发现的概率，不是身份认证。
- 对外已由 nginx 统一提供 HTTPS（`sub.minor.link`）；3000 端口仅限服务器本机访问。
- 不要把 SSH 私钥内容写入仓库。部署时只传入私钥路径。
- 如果这份文档公开，应先更换 API 前缀（步骤见 2.1 注意事项）。
- 防火墙/安全组**不要**放行 3000 端口（当前配置：仅 nginx 80/443/9090 对外）。

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

公网验证（当前走 nginx 域名，3000 端口对外不通属正常）：

```bash
curl -fsS \
  https://sub.minor.link/<PREFIX>/api/utils/env
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

安装方式：修改脚本头部的 `<PREFIX>`、`<PUBLIC_BASE>` 和 `<SERVER_IP>` 为实际部署值（`PUBLIC_BASE` 是客户端访问用的对外基地址，当前为 `https://sub.minor.link`），然后上传到服务器：

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
PUBLIC_BASE='<PUBLIC_BASE>'
SERVER_IP='<SERVER_IP>'
```

脚本只保留快照模式（历史版本曾包含实时模式与 artifact 定时任务，2026-09-02 移除：实时 `/download` 只能输出节点列表，无法生成完整配置，与生产需求不符；节点自动刷新改由 `sub-store-refresh` 定时任务负责，见 18.1 节）。

### 13.1 菜单结构

脚本启动后显示主菜单：

```text
Sub-Store 订阅管理

  快照模式（完整配置，节点自动刷新见 sub-store-refresh 定时任务）
    1. 新增订阅（转换并发布）
    2. 查看已发布订阅
    3. 修改订阅（重新转换并覆盖）
    4. 删除订阅
    0. 退出
```

- **快照模式 1-4**：转换并发布为托管文件；发布同名文件即覆盖，URL 不变。
- **退出**：退出脚本。

### 13.2 发布输出

发布成功后输出访问地址：

```text
订阅链接：
  <PUBLIC_BASE>/<PREFIX>/share/file/<NAME>
```

当前 `PUBLIC_BASE` 为 `https://sub.minor.link`。

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
- 节点自动刷新不在本脚本内：由 `sub-store-refresh` 定时任务负责（见 18.1 节）。

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

### 18.1 快照自动刷新（当前生产使用方案，2026-09-02 配置）

**背景**：实时模式 `/download` 只输出节点列表，无法生成白名单/策略组/Loyalsoldier 规则的完整配置（这些是旧脚本快照流程自己拼接的，不是 Sub-Store 后端功能）。既要完整配置又要节点自动保鲜，用本方案：crontab 定时执行无交互刷新脚本，同名覆盖发布，`/share/file` 订阅 URL 永不变化。

部署组件：

| 组件 | 路径 | 说明 |
| --- | --- | --- |
| 刷新脚本 | `/usr/local/bin/sub-store-refresh` | python3，无第三方依赖 |
| 订阅配置 | `/etc/sub-store-refresh.json` | 权限 0600，记录上游 URL 与策略模式 |
| 定时任务 | crontab `23 * * * *` | 每小时第 23 分执行 |
| 日志 | `/var/log/sub-store-refresh.log` | 追加写入 |

配置格式（`/etc/sub-store-refresh.json`）：

```json
{
  "api": "http://127.0.0.1:3000/<PREFIX>/api",
  "subs": [
    {
      "name": "JMS",
      "url": "<上游订阅 URL>",
      "mode": "whitelist",
      "rule_source": "github-proxy"
    }
  ]
}
```

- `mode`：`whitelist` 或 `blacklist`，与交互脚本快照模式的规则策略一致。
- `rule_source`：`github-proxy`（推荐）/ `jsdelivr-proxy` / `jsdelivr`。
- 刷新失败时保留旧内容不覆盖，退出码非 0。
- 新增/更换上游订阅：编辑 `subs` 数组后手动跑一次 `sub-store-refresh` 验证。
- 目标文件必须已存在（脚本只 PATCH 覆盖，不创建），首次发布仍用交互脚本菜单 1。

当前已配置订阅：

| 名称 | 上游 | 策略 |
| --- | --- | --- |
| JMS | `https://jmssub.net/members/getsub.php?service=867908&id=...` | whitelist |
| US-COMPANY | 待用户提供上游 URL | - |
| ~~ip-test~~ | - | 已废弃删除（2026-09-02） |

手动操作：

```bash
/usr/local/bin/sub-store-refresh          # 立即刷新全部
tail /var/log/sub-store-refresh.log       # 看历史执行记录
crontab -l                                # 查看定时任务
```

**历史说明**：脚本曾提供实时模式（`/api/subs` + `/download` 链接，配合 Sub-Store 原生 artifact 定时任务），因其只能输出节点列表、无法生成完整配置，已于 2026-09-02 从脚本与文档中移除，服务器上已导入的实时订阅（JMS）也已删除。

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
# 定时刷新任务
crontab -l | grep -v sub-store-refresh | crontab -
rm -f /usr/local/bin/sub-store-refresh
rm -f /etc/sub-store-refresh.json
rm -f /var/log/sub-store-refresh.log

# 后端服务
systemctl disable --now sub-store
rm -f /etc/systemd/system/sub-store.service
systemctl daemon-reload

# 交互脚本与其余组件
rm -f /usr/local/bin/sub-store-convert
rm -f /etc/sub-store.env
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
- [ ] 公网 `https://sub.minor.link/<PREFIX>/api/utils/env` 可访问
- [ ] Mihomo 节点转换成功
- [ ] Clash Verge 完整配置生成成功
- [ ] Shadowrocket 订阅 URL 生成成功
- [ ] 同名订阅更新成功
- [ ] 菜单式操作：新增、查看、修改、删除
- [ ] 删除操作使用序号选择 + 二次确认
- [ ] crontab 存在 `23 * * * * sub-store-refresh` 定时任务
- [ ] `sub-store-refresh` 手动执行成功，`/share/file/JMS` 返回 200 且内容更新
- [ ] `/usr/local/bin/sub-store-convert` 与仓库脚本一致（占位符替换后 diff 为空）
- [ ] Swap 2GB 配置完成
- [ ] 在线规则通过 `PROXY` 下载
- [ ] 重复 GEOIP 和额外 MMDB 初始化已移除
- [ ] 后端服务最终状态为 `active`

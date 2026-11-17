# VPN 换 IP 与 Sub-Store 订阅同步

本地入口：[`scripts/update-vpn-ip.py`](../../scripts/update-vpn-ip.py)。

用于 VPN 服务器更换公网 IP 后，读取新 IP 上的 sing-box 配置，更新 Sub-Store 已发布的 Mihomo 快照，并持久记录本地 SSH 地址。默认目标是 `US-COMPANY`，客户端订阅 URL 不变。

> 本脚本不会向云服务商申请或更换 IP；新 IP 必须已经分配给原 VPN 服务器，且原 SSH 密钥仍可登录。

## 快速使用

在项目根目录执行。下方 `192.0.2.20` 是文档保留地址，请替换为真实新 IP：

```bash
# 1. 只连接检查，预览计划
direnv exec . python3 scripts/update-vpn-ip.py 192.0.2.20 --dry-run

# 2. 确认目标正确后正式执行
direnv exec . python3 scripts/update-vpn-ip.py 192.0.2.20

# 3. .envrc 已被更新，重新授权 direnv 加载
direnv allow .
```

执行成功后，在客户端刷新原订阅即可。无需重启 VPN 或 Sub-Store 服务。

## 首次配置

本机需要 Python 3、OpenSSH、Git 和已安装 hook 的 direnv。脚本仅使用 Python 标准库，本机不需要 PyYAML。

已有 `.envrc` 时不要覆盖；新机器可执行：

```bash
cp .envrc.example .envrc
chmod 0600 .envrc
# 在本地编辑器填写真实配置，然后授权加载
direnv allow .
```

脚本必需的环境变量：

| 变量 | 用途 |
| --- | --- |
| `VPN_SSH_HOST` | 本机记录的 VPN 地址，成功后自动更新为输入的新 IP |
| `VPN_SSH_PORT` | VPN SSH 端口，不是代理端口 |
| `VPN_SSH_USER` | VPN SSH 用户 |
| `VPN_SSH_KEY` | 本机 VPN SSH 私钥路径 |
| `SUB_STORE_SSH_HOST` | Sub-Store 所在服务器地址，换 VPN IP 不修改此值 |
| `SUB_STORE_SSH_PORT` | Sub-Store SSH 端口 |
| `SUB_STORE_SSH_USER` | Sub-Store SSH 用户 |
| `SUB_STORE_SSH_KEY` | 本机 Sub-Store SSH 私钥路径 |

新 IP 直接用于此次 VPN SSH 连接；不要求先手动修改 `VPN_SSH_HOST`。其他变量保持原值。

API 前缀在 SSH 远端从 `/etc/sub-store.env` 读取，不把本机整份 `.envrc` 上传到服务器。完整环境变量模板见 [`.envrc.example`](../../.envrc.example)。

## 实际执行流程

1. **检查新 IP 的 VPN。** 确认 sing-box 正在运行且配置校验通过，读取主配置及 `conf/*.json` 中的 VLESS-REALITY 入站。
2. **读取最新节点参数。** 获取端口、UUID、Flow、SNI、REALITY 公钥和 Short ID；不复用旧订阅里的认证信息。私钥不会被传回本机，节点凭据不输出到终端。
3. **读取 Sub-Store 当前快照。** 通过 SSH 执行远端辅助代码，调用服务器本机 API，不直接改运行中的 JSON 数据文件。
4. **生成修改计划。** 只更新目标节点；名称含旧 IP 时同步改名及策略组、规则等引用。保留其他节点、文件元数据和分流策略。YAML 会重新排版，不保留注释。
5. **备份、写入和校验。** 复核快照摘要，备份原文件对象，通过 `PATCH /api/file/:name` 同名覆盖内容，再读取存储内容及 `/share/file/:name` 验证。重复执行无变更时不重新覆盖订阅。
6. **持久更新本地。** 线上校验成功后，原子更新 `.envrc` 中的 `VPN_SSH_HOST`，追加换 IP 历史。

这与 `sub-store-convert` 的“修改订阅”菜单最终效果一致，但不会重新生成整套规则，也不模拟交互输入；脚本直接调用同一个文件更新 API。

## 参数

```bash
python3 scripts/update-vpn-ip.py --help
```

| 参数 | 默认值 / 含义 |
| --- | --- |
| `ip` | 必填，新 IPv4 或 IPv6 地址 |
| `--dry-run` | 只读检查，不写订阅、备份、本地配置或历史 |
| `--subscription NAME` | 默认 `US-COMPANY`，指定已有的本地快照 |
| `--node-name NAME` | 快照中存在多个 REALITY 节点时，指定原节点名称 |
| `--inbound-tag TAG` | VPN 配置中存在多个 REALITY 入站时，指定入站 tag |

例如：

```bash
direnv exec . python3 scripts/update-vpn-ip.py 192.0.2.20 \
  --subscription MY-VPN \
  --node-name '自建主节点' \
  --inbound-tag 'VLESS-REALITY-443.json' \
  --dry-run
```

## 记录与备份

| 位置 | 内容 | 是否提交 |
| --- | --- | --- |
| 本机 `.envrc` | SSH 地址、密钥路径等真实配置；权限 `0600` | 否，已忽略 |
| 本机 `.direnv/vpn-ip-history.jsonl` | UTC 时间、前后 IP、订阅名及服务器备份路径；权限 `0600` | 否，`.direnv/` 已忽略 |
| 订阅服务器 `/var/backups/sub-store-vpn/` | 更新前的完整文件对象，含原节点凭据；目录 `0700`、文件 `0600` | 否，不复制进仓库 |

历史中 `old_ssh_ip` 与 `old_subscription_ip` 可能不同：前者是本机原来记录的地址，后者是订阅快照原来使用的地址。线上快照更新成功前，本机 SSH 地址不会提前覆盖。

## 适用范围与安全限制

- VPN 采用当前 233boy 部署布局：`/etc/sing-box/bin/sing-box`、`/etc/sing-box/config.json`、`/etc/sing-box/conf/*.json`，具备 `jq` 和 systemd。
- 目前只支持单用户 VLESS-REALITY TCP；公钥来自配置中的 `public_key_...` 标记。脚本不会重新生成密钥，参数缺失或节点选择不唯一时会停止。
- 订阅服务器需要 Python 3.6+、PyYAML，以及 `127.0.0.1:3000` 上运行中的 Sub-Store。SSH 用户需有环境文件读取、备份和远端锁文件写入权限，当前部署使用 root。
- 仅支持没有后处理器的本地 Mihomo 快照。若目标被 `/etc/sub-store-refresh.json` 定时刷新管理，会拒绝修改，避免随后被上游覆盖。
- 不修改 JMS、不增加备用节点、不轮换 API 前缀、不重启服务，也不修改 VPN 服务器配置。
- SSH 主机密钥已知但不匹配时会停止，不关闭校验。首次访问新 IP 使用 `accept-new`，可能更新本机 `known_hosts`；预览模式也遵循这一行为。
- 本地与远端有脚本间互斥锁，并在写入前复核快照摘要。但 Sub-Store API 没有原子比较交换接口，操作时不要通过其他工具同时编辑目标订阅。
- 自动校验确认配置存储和输出一致，**不等于实际客户端代理连通性测试**。
- 环境变量化不会消除 Git 历史中的旧凭据。历史 API 前缀的轮换需要另行操作，轮换会改变客户端订阅 URL。

## 失败时怎么办

- **VPN 连接或参数检查失败：** 不会改订阅或本地 SSH 地址。检查新 IP、SSH 端口、密钥、`known_hosts` 和入站配置。
- **更新后的校验失败：** 脚本尽可能恢复旧内容；若发现内容被其他操作改动，则拒绝盲目回滚，并保留备份供核对。
- **写入期间 SSH 中断：** 不能据此认定未更新。先重新授权 direnv（如需要），再执行 `--dry-run` 核对当前状态，并查看服务器备份；不要反复强制覆盖。
- **线上成功但本地落盘失败：** 按提示检查本地权限/磁盘，手动修正 `.envrc` 的 `VPN_SSH_HOST`，再 `direnv allow .`。
- **direnv 提示 blocked：** `.envrc` 改变后需要重新授权；这是 direnv 的正常安全机制。

手动恢复服务器备份时，应从备份 JSON 提取 `content`，通过 Sub-Store 文件 API 恢复同名快照，不要直接覆盖运行中的 `/var/lib/sub-store/sub-store.json`。恢复旧节点地址也不代表旧 IP 已重新可用。

## 测试与相关文件

```bash
# 模拟 SSH/API 的离线测试，不访问真实服务器
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test-update-vpn-ip.py

# 交互转换脚本的环境变量兼容性检查
python3 docs/deployment/test-sub-store-convert.py
bash -n docs/deployment/sub-store-convert.sh
shellcheck docs/deployment/sub-store-convert.sh
```

- [`scripts/sub_store_vpn_remote.py`](../../scripts/sub_store_vpn_remote.py)：通过 SSH 标准输入执行的辅助代码，不安装到远端，也不把凭据放在命令行参数里。
- [完整后端部署记录](sub-store-backend-deployment.md)：环境变量配置、交互脚本与定时刷新等运维说明。

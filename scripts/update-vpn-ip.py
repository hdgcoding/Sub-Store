#!/usr/bin/env python3
"""Read the VPN's live REALITY configuration, update Sub-Store, remember the IP."""

import argparse
import base64
import datetime
import fcntl
import ipaddress
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import uuid


ROOT = pathlib.Path(__file__).resolve().parent.parent
REMOTE_HELPER = pathlib.Path(__file__).with_name("sub_store_vpn_remote.py")
VPN_QUERY = r"""
set -eu
systemctl is-active --quiet sing-box
command -v jq >/dev/null
/etc/sing-box/bin/sing-box check -c /etc/sing-box/config.json -C /etc/sing-box/conf >/dev/null 2>&1
jq -s '[.[] | . as $config | .inbounds[]? | select(.type == "vless") | {
  tag, port: .listen_port, users, transport,
  tls_enabled: .tls.enabled, reality_enabled: .tls.reality.enabled,
  server_name: .tls.server_name, short_ids: .tls.reality.short_id,
  public_keys: [$config.outbounds[]?.tag // empty |
    select(startswith("public_key_")) | ltrimstr("public_key_")]
}]' /etc/sing-box/config.json /etc/sing-box/conf/*.json
"""


class UpdateError(Exception):
    pass


def required(name):
    value = os.environ.get(name, "")
    if not value:
        raise UpdateError("缺少环境变量 {}，请先 direnv allow .。".format(name))
    return value


def ssh_arguments(prefix, host=None):
    host = host or required(prefix + "_SSH_HOST")
    user = required(prefix + "_SSH_USER")
    port = required(prefix + "_SSH_PORT")
    key = pathlib.Path(required(prefix + "_SSH_KEY")).expanduser()
    if not re.fullmatch(r"[A-Za-z0-9_.:\[\]-]+", host) or host.startswith("-"):
        raise UpdateError("SSH 主机配置无效。")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", user):
        raise UpdateError("SSH 用户配置无效。")
    if not port.isdigit() or not 1 <= int(port) <= 65535 or not key.is_file():
        raise UpdateError("SSH 端口或本地密钥路径无效。")
    return [
        "ssh", "-i", str(key), "-p", port, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
        user + "@" + host,
    ]


def ssh_json(arguments, command, stdin, label):
    try:
        result = subprocess.run(
            arguments + [command], input=stdin, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise UpdateError(label + " SSH 连接失败或超时，请核对连接和 known_hosts。") from None
    if result.returncode:
        raise UpdateError(label + " SSH/读取失败，请核对服务、密钥及 known_hosts。")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise UpdateError(label + " 返回格式不正确（已隐藏输出，避免泄露凭据）。") from None


def node_from_config(configs, host, inbound_tag=None):
    candidates = [
        entry for entry in configs
        if entry.get("tls_enabled") and entry.get("reality_enabled")
        and (inbound_tag is None or entry.get("tag") == inbound_tag)
    ]
    if len(candidates) != 1:
        raise UpdateError("无法唯一定位 VPN REALITY 入站，请通过 --inbound-tag 指定。")
    entry = candidates[0]
    if entry.get("transport"):
        raise UpdateError("目前仅支持没有额外 transport 的 VLESS-REALITY TCP 入站。")
    users, keys, short_ids = (
        entry.get("users", []), entry.get("public_keys", []), entry.get("short_ids", [])
    )
    if len(users) != 1 or len(keys) != 1 or not short_ids:
        raise UpdateError("需要单用户、单公钥的 233boy REALITY 配置及至少一个 Short ID。")
    try:
        user_uuid = str(uuid.UUID(users[0]["uuid"]))
        public_key = keys[0]
        if len(base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))) != 32:
            raise ValueError("public key")
        port = int(entry["port"])
        short_id = short_ids[0]
        if not 1 <= port <= 65535 or not re.fullmatch(r"(?:[0-9a-fA-F]{2}){0,8}", short_id):
            raise ValueError("port or short id")
        if users[0].get("flow", "") not in ("", "xtls-rprx-vision"):
            raise ValueError("flow")
        if not isinstance(entry.get("server_name"), str) or not entry["server_name"]:
            raise ValueError("SNI")
    except (KeyError, ValueError, TypeError):
        raise UpdateError("VPN 节点参数不完整或格式无效，未修改订阅。") from None
    return {
        "server": host, "port": port, "uuid": user_uuid,
        "public_key": public_key, "short_id": short_id,
        "server_name": entry["server_name"], "flow": users[0].get("flow", ""),
    }


def remote_sync(arguments, payload):
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    code = REMOTE_HELPER.read_text(encoding="utf-8")
    code += "\nimport base64\nrun_payload(json.loads(base64.b64decode({!r})))\n".format(encoded)
    response = ssh_json(arguments, "python3 -B -", code, "Sub-Store")
    if not response.get("ok"):
        raise UpdateError(response.get("error", "Sub-Store 操作失败。"))
    return response["result"]


def envrc_with_host(text, host):
    pattern = re.compile(r"^export VPN_SSH_HOST=[^\r\n]*$", re.MULTILINE)
    if len(pattern.findall(text)) != 1:
        raise UpdateError(".envrc 必须有且只有一行 export VPN_SSH_HOST=...。")
    return pattern.sub("export VPN_SSH_HOST=" + shlex.quote(host), text)


def save_local(root, original, updated, record):
    envrc = root / ".envrc"
    if envrc.read_text(encoding="utf-8") != original:
        raise UpdateError("线上已验证成功，但 .envrc 被并发修改，未覆盖；请手动同步 VPN_SSH_HOST。")
    state = root / ".direnv"
    descriptor, filename = tempfile.mkstemp(prefix="vpn-env-", dir=str(state))
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(filename, str(envrc))
    finally:
        if os.path.exists(filename):
            os.unlink(filename)
    history = state / "vpn-ip-history.jsonl"
    descriptor = os.open(str(history), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.chmod(str(history), 0o600)
    with os.fdopen(descriptor, "a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def execute(args):
    try:
        host = str(ipaddress.ip_address(args.ip))
    except ValueError:
        raise UpdateError("请输入有效的新 IPv4 或 IPv6 地址。") from None
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.subscription):
        raise UpdateError("订阅名称只能包含字母、数字、点、下划线和短横线。")
    envrc = ROOT / ".envrc"
    if not envrc.is_file() or envrc.is_symlink():
        raise UpdateError("项目根目录缺少普通文件 .envrc，请先配置。")
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", ".envrc"], cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if ignored.returncode:
        raise UpdateError(".envrc 未被 Git 忽略，已停止以保护访问凭据。")
    original = envrc.read_text(encoding="utf-8")
    updated = envrc_with_host(original, host)
    old_ssh_ip = required("VPN_SSH_HOST")
    vpn = ssh_arguments("VPN", host)
    sub_store = ssh_arguments("SUB_STORE")
    print("1. 读取新 IP 上的 sing-box 配置（不输出节点凭据）……", flush=True)
    config = ssh_json(vpn, "sh -s", VPN_QUERY, "VPN")
    node = node_from_config(config, host, args.inbound_tag)
    # Read structured node data instead of logging or persisting a secret URI.
    # Updating the existing snapshot preserves its rules and policy groups.
    payload = {
        "node": node, "subscription": args.subscription,
        "node_name": args.node_name, "dry_run": True,
    }
    print("2. 读取 Sub-Store 快照并检查更新计划……", flush=True)
    summary = remote_sync(sub_store, payload)
    print("   {}：{} → {}:{}".format(
        args.subscription, summary["old_ip"], host, node["port"]
    ))
    print("   节点名称：{} → {}".format(summary["old_name"], summary["new_name"]))
    if args.dry_run:
        print("预览完成：未修改订阅、.envrc 或换 IP 记录。")
        return
    print("3. 备份、更新并验证 Sub-Store 对外快照……", flush=True)
    payload.update(dry_run=False, expected_digest=summary["snapshot_digest"])
    try:
        result = remote_sync(sub_store, payload)
    except UpdateError as error:
        raise UpdateError(
            str(error) + " 写入阶段已启动，请先核对线上状态及 /var/backups/sub-store-vpn，"
            "不要假定网络中断意味着未更新；本地 SSH IP 尚未修改。"
        ) from None
    record = {
        "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "old_ssh_ip": old_ssh_ip, "new_ip": host,
        "old_subscription_ip": summary["old_ip"],
        "subscription": args.subscription, "backup": result.get("backup"),
    }
    try:
        save_local(ROOT, original, updated, record)
    except OSError:
        raise UpdateError("线上已验证成功，但本地记录写入失败，请手动同步 .envrc 并检查磁盘权限。") from None
    print("成功：订阅已验证，本机 .envrc 的 VPN_SSH_HOST 已更新。")
    print("换 IP 记录：.direnv/vpn-ip-history.jsonl（已被 Git 忽略）。")
    if result.get("backup"):
        print("服务器备份：" + result["backup"])
    print("请运行 direnv allow . 重新授权；客户端刷新原订阅即可，无需更换链接。")


def main():
    parser = argparse.ArgumentParser(
        description="从新 IP 读取 VLESS-REALITY 配置，更新 Sub-Store 快照并记录 SSH IP。"
    )
    parser.add_argument("ip", help="VPN 服务器的新 IPv4/IPv6 地址")
    parser.add_argument("--dry-run", action="store_true", help="只连接检查并预览，不写订阅和本地记录")
    parser.add_argument("--subscription", default="US-COMPANY", help="目标快照名称（默认 US-COMPANY）")
    parser.add_argument("--node-name", help="目标快照中存在多个 REALITY 节点时指定名称")
    parser.add_argument("--inbound-tag", help="VPN 存在多个 REALITY 入站时指定 tag")
    args = parser.parse_args()
    try:
        if args.dry_run:
            execute(args)
        else:
            state = ROOT / ".direnv"
            state.mkdir(mode=0o700, exist_ok=True)
            os.chmod(str(state), 0o700)
            with (state / "vpn-ip-update.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                execute(args)
    except BlockingIOError:
        print("失败：另一个换 IP 操作正在执行。", file=sys.stderr)
        return 1
    except UpdateError as error:
        print("失败：" + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("失败：检查未完成，已隐藏可能含凭据的异常详情；请核对线上状态后再重试。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

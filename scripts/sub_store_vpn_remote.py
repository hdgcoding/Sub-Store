"""Sub-Store SSH helper, sent over stdin; compatible with server Python 3.6."""

import copy
import datetime
import hashlib
import json
import os
import pathlib
import re
import shlex
import urllib.parse
import urllib.request
import uuid


class SyncError(Exception):
    pass


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def api_prefix(filename="/etc/sub-store.env"):
    for line in pathlib.Path(filename).read_text().splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key == "SUB_STORE_FRONTEND_BACKEND_PATH":
            parts = shlex.split(value)
            if len(parts) == 1 and re.match(r"^/[A-Za-z0-9_-]+$", parts[0]):
                return parts[0]
    raise SyncError("无法从服务器环境文件读取有效 API 前缀。")


class API:
    def __init__(self, prefix):
        self.base = "http://127.0.0.1:3000" + prefix
        # Never send loopback API credentials through an inherited HTTP proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, body=None, raw=False):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "PATCH",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                text = response.read().decode("utf-8")
            if raw:
                return text
            result = json.loads(text)
            if result.get("status") != "success":
                raise ValueError("API status")
            return result["data"]
        except Exception:
            # Do not propagate URLs (API prefix) or response bodies (node secrets).
            raise SyncError("Sub-Store API 请求失败，请检查服务和权限。") from None


def update_profile(profile, node, selected_name=None):
    """Update one REALITY node and its references, leaving other policy data intact."""
    result = copy.deepcopy(profile)
    if not isinstance(result, dict) or not isinstance(result.get("proxies"), list):
        raise SyncError("订阅不是完整 Mihomo 配置。")
    candidates = [
        proxy
        for proxy in result["proxies"]
        if isinstance(proxy, dict)
        and proxy.get("type") == "vless"
        and isinstance(proxy.get("reality-opts"), dict)
        and (selected_name is None or proxy.get("name") == selected_name)
    ]
    if len(candidates) != 1:
        raise SyncError("无法唯一定位 REALITY 节点，请通过 --node-name 指定。")
    proxy = candidates[0]
    if proxy.get("network", "tcp") != "tcp":
        raise SyncError("目前只支持 VLESS-REALITY TCP 节点。")
    old_host, old_name = proxy.get("server"), proxy.get("name")
    if not isinstance(old_host, str) or not old_host or not isinstance(old_name, str) or not old_name:
        raise SyncError("原节点缺少地址或名称。")
    new_name = old_name.replace(old_host, node["server"])
    if any(p is not proxy and p.get("name") == new_name for p in result["proxies"]):
        raise SyncError("更新后的节点名称与其他节点冲突。")
    proxy.update(
        name=new_name,
        type="vless",
        server=node["server"],
        port=node["port"],
        uuid=node["uuid"],
        flow=node["flow"],
        tls=True,
        network="tcp",
        servername=node["server_name"],
    )
    proxy.pop("sni", None)
    proxy.pop("skip-cert-verify", None)
    proxy.setdefault("client-fingerprint", "chrome")
    proxy["reality-opts"].update(
        {"public-key": node["public_key"], "short-id": node["short_id"]}
    )
    if old_name != new_name:
        for group in result.get("proxy-groups", []):
            if "proxies" in group:
                group["proxies"] = [
                    new_name if name == old_name else name for name in group["proxies"]
                ]
        for other in result["proxies"]:
            if other.get("dialer-proxy") == old_name:
                other["dialer-proxy"] = new_name
        for section in ("rule-providers", "proxy-providers"):
            for provider in result.get(section, {}).values():
                if provider.get("proxy") == old_name:
                    provider["proxy"] = new_name
        for index, rule in enumerate(result.get("rules", [])):
            for suffix in ("", ",no-resolve"):
                ending = "," + old_name + suffix
                if rule.endswith(ending):
                    result["rules"][index] = rule[:-len(ending)] + "," + new_name + suffix
                    break
    return result, {
        "old_ip": old_host,
        "new_ip": node["server"],
        "old_name": old_name,
        "new_name": new_name,
        "changed": result != profile,
    }


def backup_file(item, directory="/var/backups/sub-store-vpn"):
    directory = pathlib.Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(str(directory), 0o700)
    filename = "{}-{}-{}.json".format(
        item["name"],
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:8],
    )
    path = directory / filename
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(item, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    return str(path)


def apply_update(api, path, share_path, original, content, profile, yaml):
    """Verify both stored and served content; conservatively roll back on failure."""
    try:
        api.request(path, {"content": content})
        current = api.request(path.replace("/api/file/", "/api/wholeFile/"))
        served = yaml.safe_load(api.request(share_path, raw=True))
        if current.get("content") != content or served != profile:
            raise SyncError("更新后内容校验失败。")
    except Exception:
        try:
            current = api.request(path.replace("/api/file/", "/api/wholeFile/"))
            if current.get("content") == content:
                api.request(path, {"content": original})
                restored = api.request(path.replace("/api/file/", "/api/wholeFile/"))
                if restored.get("content") != original:
                    raise ValueError("restore verification")
            elif current.get("content") != original:
                raise ValueError("concurrent update")
        except Exception:
            raise SyncError("更新失败且无法安全回滚；请用服务器备份核对，勿盲目重试。") from None
        raise SyncError("更新或校验失败，已确认原订阅内容保留/恢复。") from None


def synchronize(payload):
    try:
        import yaml
    except ImportError:
        raise SyncError("订阅服务器缺少 PyYAML；本机不需要安装。") from None

    name = payload["subscription"]
    if not re.match(r"^[A-Za-z0-9._-]+$", name):
        raise SyncError("订阅名称无效。")
    refresh = pathlib.Path("/etc/sub-store-refresh.json")
    if refresh.exists():
        entries = json.loads(refresh.read_text()).get("subs", [])
        if any(entry.get("name") == name for entry in entries):
            raise SyncError("该订阅由自动刷新管理，拒绝修改会被覆盖的快照。")
    api = API(api_prefix())
    encoded = urllib.parse.quote(name, safe="")
    whole_path = "/api/wholeFile/" + encoded
    item = api.request(whole_path)
    if item.get("source") != "local" or item.get("process"):
        raise SyncError("只支持没有后处理器的本地快照订阅。")
    original = item["content"]
    profile = yaml.safe_load(original)
    updated, summary = update_profile(profile, payload["node"], payload.get("node_name"))
    summary["snapshot_digest"] = digest(item)
    summary["subscription"] = name
    content = yaml.safe_dump(updated, allow_unicode=True, default_flow_style=False)
    if yaml.safe_load(content) != updated:
        raise SyncError("配置序列化校验失败，未写入。")
    if payload["dry_run"]:
        return summary
    if payload["expected_digest"] != summary["snapshot_digest"]:
        raise SyncError("订阅在预览后发生变化，已停止，请重新运行。")
    if not summary["changed"]:
        if yaml.safe_load(api.request("/share/file/" + encoded, raw=True)) != profile:
            raise SyncError("节点无需变更，但对外快照校验失败；未修改。")
        return summary
    backup = backup_file(item)
    summary["backup"] = backup
    try:
        # Recheck after taking the backup, before issuing the PATCH.
        if digest(api.request(whole_path)) != summary["snapshot_digest"]:
            raise SyncError("订阅发生并发更新，已停止。")
        apply_update(
            api, "/api/file/" + encoded, "/share/file/" + encoded,
            original, content, updated, yaml,
        )
    except SyncError as error:
        raise SyncError(str(error) + " 备份：" + backup) from None
    return summary


def run_payload(payload):
    try:
        if payload["dry_run"]:
            result = synchronize(payload)
        else:
            import fcntl
            descriptor = os.open(
                "/run/lock/sub-store-vpn-update.lock", os.O_CREAT | os.O_RDWR, 0o600
            )
            with os.fdopen(descriptor, "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = synchronize(payload)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except SyncError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
    except Exception:
        print(json.dumps({"ok": False, "error": "远端检查失败；未输出敏感异常详情。"}))

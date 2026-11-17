"""Offline regression tests. No real SSH, credentials, PyYAML or API required."""

import copy
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock


HERE = pathlib.Path(__file__).resolve().parent


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, str(HERE / filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


local = load_module("vpn_ip_local", "update-vpn-ip.py")
remote = load_module("vpn_ip_remote", "sub_store_vpn_remote.py")
NODE = {
    "server": "192.0.2.20", "port": 443,
    "uuid": "00000000-0000-4000-8000-000000000001",
    "flow": "xtls-rprx-vision", "server_name": "example.com",
    "public_key": "A" * 43, "short_id": "aabbccdd",
}
OLD_NAME = "reality-192.0.2.10"
NEW_NAME = "reality-192.0.2.20"
PROFILE = {
    "mixed-port": 7890,
    "proxies": [{
        "name": OLD_NAME, "type": "vless", "server": "192.0.2.10",
        "port": 8443, "uuid": "old-user", "network": "tcp", "tls": True,
        "flow": "xtls-rprx-vision", "servername": "old.example.com",
        "client-fingerprint": "chrome", "udp": True,
        "reality-opts": {"public-key": "old-public-key", "short-id": "0011"},
    }],
    "proxy-groups": [
        {"name": "PROXY", "type": "select", "proxies": ["AUTO", OLD_NAME]},
        {"name": "AUTO", "type": "url-test", "proxies": [OLD_NAME]},
    ],
    "rule-providers": {"direct": {"url": "https://example.com/direct.txt"}},
    "rules": ["RULE-SET,direct,DIRECT", "MATCH,PROXY"],
}
JSON_YAML = types.SimpleNamespace(
    safe_load=json.loads,
    safe_dump=lambda value, **kwargs: json.dumps(value),
)


class FakeAPI:
    def __init__(self):
        self.item = {
            "name": "US-COMPANY", "source": "local", "process": [],
            "content": json.dumps(PROFILE), "displayName": "Keep display name",
        }
        self.calls = []
        self.bad_share = False
        self.lost_patch_reply = False
        self.concurrent_content = None

    def request(self, path, body=None, raw=False):
        self.calls.append((path, body))
        if body is not None:
            self.item.update(body)
            if self.lost_patch_reply:
                self.lost_patch_reply = False
                raise remote.SyncError("simulated lost reply")
            return copy.deepcopy(self.item)
        if raw:
            if self.concurrent_content:
                self.item["content"] = self.concurrent_content
            return "{}" if self.bad_share else self.item["content"]
        return copy.deepcopy(self.item)


class ProfileTests(unittest.TestCase):
    def test_updates_all_live_parameters_and_group_references(self):
        original = copy.deepcopy(PROFILE)
        result, summary = remote.update_profile(PROFILE, NODE)
        proxy = result["proxies"][0]
        self.assertEqual(proxy["server"], NODE["server"])
        self.assertEqual(proxy["uuid"], NODE["uuid"])
        self.assertEqual(proxy["port"], NODE["port"])
        self.assertEqual(proxy["servername"], NODE["server_name"])
        self.assertEqual(proxy["reality-opts"]["public-key"], NODE["public_key"])
        self.assertEqual(proxy["reality-opts"]["short-id"], NODE["short_id"])
        self.assertTrue(proxy["udp"])
        self.assertEqual(result["proxy-groups"][0]["proxies"], ["AUTO", NEW_NAME])
        self.assertEqual(result["proxy-groups"][1]["proxies"], [NEW_NAME])
        self.assertEqual(result["rules"], PROFILE["rules"])
        self.assertEqual(result["rule-providers"], PROFILE["rule-providers"])
        self.assertEqual(PROFILE, original)
        self.assertTrue(summary["changed"])

    def test_repeat_is_idempotent(self):
        first, _ = remote.update_profile(PROFILE, NODE)
        second, summary = remote.update_profile(first, NODE)
        self.assertEqual(first, second)
        self.assertFalse(summary["changed"])

    def test_multiple_nodes_require_explicit_selector(self):
        profile = copy.deepcopy(PROFILE)
        extra = copy.deepcopy(profile["proxies"][0])
        extra["name"] = "another"
        profile["proxies"].append(extra)
        with self.assertRaises(remote.SyncError):
            remote.update_profile(profile, NODE)
        result, _ = remote.update_profile(profile, NODE, OLD_NAME)
        self.assertEqual(result["proxies"][1], extra)

    def test_renames_direct_rule_provider_and_dialer_references(self):
        profile = copy.deepcopy(PROFILE)
        profile["proxies"].append({"name": "other", "type": "ss", "dialer-proxy": OLD_NAME})
        profile["rule-providers"]["direct"]["proxy"] = OLD_NAME
        profile["rules"] = ["MATCH," + OLD_NAME, "IP-CIDR,192.0.2.0/24," + OLD_NAME + ",no-resolve"]
        result, _ = remote.update_profile(profile, NODE)
        self.assertEqual(result["proxies"][1]["dialer-proxy"], NEW_NAME)
        self.assertEqual(result["rule-providers"]["direct"]["proxy"], NEW_NAME)
        self.assertEqual(result["rules"], [
            "MATCH," + NEW_NAME, "IP-CIDR,192.0.2.0/24," + NEW_NAME + ",no-resolve",
        ])

    def test_wrong_protocol_and_name_collision_are_rejected(self):
        profile = copy.deepcopy(PROFILE)
        profile["proxies"][0]["network"] = "ws"
        with self.assertRaises(remote.SyncError):
            remote.update_profile(profile, NODE)
        profile = copy.deepcopy(PROFILE)
        profile["proxies"].append({"name": NEW_NAME, "type": "ss"})
        with self.assertRaises(remote.SyncError):
            remote.update_profile(profile, NODE)


class APIUpdateTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.old_content = self.api.item["content"]
        self.profile, _ = remote.update_profile(PROFILE, NODE)
        self.new_content = json.dumps(self.profile)

    def apply(self):
        remote.apply_update(
            self.api, "/api/file/US-COMPANY", "/share/file/US-COMPANY",
            self.old_content, self.new_content, self.profile, JSON_YAML,
        )

    def test_patch_only_content_and_verify_served_profile(self):
        self.apply()
        self.assertEqual(self.api.item["content"], self.new_content)
        self.assertEqual(self.api.item["displayName"], "Keep display name")
        patches = [body for _, body in self.api.calls if body is not None]
        self.assertEqual(patches, [{"content": self.new_content}])
        self.assertIn(("/share/file/US-COMPANY", None), self.api.calls)

    def test_bad_share_rolls_back(self):
        self.api.bad_share = True
        with self.assertRaisesRegex(remote.SyncError, "保留/恢复"):
            self.apply()
        self.assertEqual(self.api.item["content"], self.old_content)

    def test_lost_patch_reply_rolls_back(self):
        self.api.lost_patch_reply = True
        with self.assertRaisesRegex(remote.SyncError, "保留/恢复"):
            self.apply()
        self.assertEqual(self.api.item["content"], self.old_content)

    def test_rollback_does_not_overwrite_concurrent_change(self):
        self.api.bad_share = True
        self.api.concurrent_content = '{"concurrent":"update"}'
        with self.assertRaisesRegex(remote.SyncError, "无法安全回滚"):
            self.apply()
        self.assertEqual(self.api.item["content"], self.api.concurrent_content)

    def test_preview_is_read_only_and_stale_plan_is_rejected(self):
        payload = {"subscription": "US-COMPANY", "node": NODE, "dry_run": True}
        with mock.patch.dict(sys.modules, {"yaml": JSON_YAML}), \
                mock.patch.object(remote, "API", return_value=self.api), \
                mock.patch.object(remote, "api_prefix", return_value="/test-prefix"), \
                mock.patch.object(remote, "backup_file") as backup:
            summary = remote.synchronize(payload)
            self.assertTrue(summary["changed"])
            self.assertTrue(all(body is None for _, body in self.api.calls))
            backup.assert_not_called()
            payload.update(dry_run=False, expected_digest="stale")
            with self.assertRaisesRegex(remote.SyncError, "预览后发生变化"):
                remote.synchronize(payload)
            backup.assert_not_called()

    def test_full_apply_backs_up_before_writing(self):
        payload = {
            "subscription": "US-COMPANY", "node": NODE, "dry_run": False,
            "expected_digest": remote.digest(self.api.item),
        }
        with mock.patch.dict(sys.modules, {"yaml": JSON_YAML}), \
                mock.patch.object(remote, "API", return_value=self.api), \
                mock.patch.object(remote, "api_prefix", return_value="/test-prefix"), \
                mock.patch.object(remote, "backup_file", return_value="/backup/test.json") as backup:
            summary = remote.synchronize(payload)
            backup.assert_called_once()
            self.assertEqual(backup.call_args[0][0]["content"], self.old_content)
            self.assertEqual(summary["backup"], "/backup/test.json")
            self.assertEqual(json.loads(self.api.item["content"]), self.profile)

    def test_unchanged_snapshot_is_verified_without_backup_or_patch(self):
        self.api.item["content"] = self.new_content
        payload = {
            "subscription": "US-COMPANY", "node": NODE, "dry_run": False,
            "expected_digest": remote.digest(self.api.item),
        }
        with mock.patch.dict(sys.modules, {"yaml": JSON_YAML}), \
                mock.patch.object(remote, "API", return_value=self.api), \
                mock.patch.object(remote, "api_prefix", return_value="/test-prefix"), \
                mock.patch.object(remote, "backup_file") as backup:
            summary = remote.synchronize(payload)
            self.assertFalse(summary["changed"])
            backup.assert_not_called()
            self.assertTrue(all(body is None for _, body in self.api.calls))
            self.assertIn(("/share/file/US-COMPANY", None), self.api.calls)

    def test_serialization_is_checked_even_in_preview(self):
        invalid_yaml = types.SimpleNamespace(
            safe_load=json.loads, safe_dump=lambda *args, **kwargs: "{}"
        )
        payload = {"subscription": "US-COMPANY", "node": NODE, "dry_run": True}
        with mock.patch.dict(sys.modules, {"yaml": invalid_yaml}), \
                mock.patch.object(remote, "API", return_value=self.api), \
                mock.patch.object(remote, "api_prefix", return_value="/test-prefix"):
            with self.assertRaisesRegex(remote.SyncError, "序列化校验失败"):
                remote.synchronize(payload)

    def test_refresh_managed_subscription_is_rejected_before_api_access(self):
        payload = {"subscription": "US-COMPANY", "node": NODE, "dry_run": True}
        config = json.dumps({"subs": [{"name": "US-COMPANY"}]})
        with mock.patch.dict(sys.modules, {"yaml": JSON_YAML}), \
                mock.patch.object(remote.pathlib.Path, "exists", return_value=True), \
                mock.patch.object(remote.pathlib.Path, "read_text", return_value=config), \
                mock.patch.object(remote, "API") as api:
            with self.assertRaisesRegex(remote.SyncError, "自动刷新管理"):
                remote.synchronize(payload)
            api.assert_not_called()

    def test_api_errors_do_not_expose_credentials(self):
        api = remote.API("/test-access-prefix")
        with mock.patch.object(api.opener, "open", side_effect=ValueError("sensitive-details")):
            with self.assertRaises(remote.SyncError) as raised:
                api.request("/api/wholeFile/test")
        self.assertNotIn("test-access-prefix", str(raised.exception))
        self.assertNotIn("sensitive-details", str(raised.exception))


class LocalStateTests(unittest.TestCase):
    def test_envrc_and_history_are_private_and_preserve_other_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / ".direnv").mkdir()
            original = "export VPN_SSH_HOST='192.0.2.10'\nexport KEEP='unchanged'\n"
            (root / ".envrc").write_text(original)
            updated = local.envrc_with_host(original, "192.0.2.20")
            record = {"old_ssh_ip": "192.0.2.10", "new_ip": "192.0.2.20"}
            local.save_local(root, original, updated, record)
            self.assertEqual((root / ".envrc").read_text(), updated)
            self.assertIn("export KEEP='unchanged'", updated)
            history = root / ".direnv/vpn-ip-history.jsonl"
            self.assertEqual(json.loads(history.read_text()), record)
            self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((root / ".envrc").stat().st_mode), 0o600)
            self.assertEqual(list((root / ".direnv").iterdir()), [history])

    def test_missing_or_duplicate_host_lines_are_rejected(self):
        for text in ("export OTHER=x\n", "export VPN_SSH_HOST=x\nexport VPN_SSH_HOST=y\n"):
            with self.assertRaises(local.UpdateError):
                local.envrc_with_host(text, NODE["server"])

    def test_concurrent_envrc_edit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / ".envrc").write_text("user edit")
            with self.assertRaisesRegex(local.UpdateError, "并发修改"):
                local.save_local(root, "original", "updated", {})
            self.assertEqual((root / ".envrc").read_text(), "user edit")

    def test_backup_is_private_and_contains_exact_original(self):
        with tempfile.TemporaryDirectory() as directory:
            item = FakeAPI().item
            path = pathlib.Path(remote.backup_file(item, directory + "/backups"))
            self.assertEqual(json.loads(path.read_text()), item)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_vpn_config_selection_validation_and_no_private_key_query(self):
        entry = {
            "tag": "reality", "tls_enabled": True, "reality_enabled": True,
            "users": [{"uuid": NODE["uuid"], "flow": NODE["flow"]}],
            "public_keys": [NODE["public_key"]], "short_ids": [NODE["short_id"]],
            "server_name": NODE["server_name"], "port": NODE["port"],
        }
        self.assertEqual(local.node_from_config([entry], NODE["server"]), NODE)
        with self.assertRaises(local.UpdateError):
            local.node_from_config([entry, entry], NODE["server"])
        self.assertEqual(
            local.node_from_config([entry, dict(entry, tag="second")], NODE["server"], "reality"),
            NODE,
        )
        invalid = dict(entry, public_keys=[])
        with self.assertRaises(local.UpdateError):
            local.node_from_config([invalid], NODE["server"])
        self.assertNotIn("private_key", local.VPN_QUERY)

    def test_orchestration_does_not_save_on_preview_or_remote_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            original = "export VPN_SSH_HOST='192.0.2.10'\n"
            (root / ".envrc").write_text(original)
            args = types.SimpleNamespace(
                ip=NODE["server"], subscription="US-COMPANY",
                node_name=None, inbound_tag=None, dry_run=True,
            )
            summary = {
                "old_ip": "192.0.2.10", "old_name": OLD_NAME,
                "new_name": NEW_NAME, "snapshot_digest": "test-digest",
            }
            with mock.patch.object(local, "ROOT", root), \
                    mock.patch.object(local.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)), \
                    mock.patch.object(local, "required", return_value="192.0.2.10"), \
                    mock.patch.object(local, "ssh_arguments", return_value=[]), \
                    mock.patch.object(local, "ssh_json", return_value=[]), \
                    mock.patch.object(local, "node_from_config", return_value=NODE), \
                    mock.patch.object(local, "remote_sync", return_value=summary) as sync, \
                    mock.patch.object(local, "save_local") as save, \
                    contextlib.redirect_stdout(io.StringIO()):
                local.execute(args)
                self.assertEqual(sync.call_count, 1)
                self.assertTrue(sync.call_args[0][1]["dry_run"])
                save.assert_not_called()
                args.dry_run = False
                sync.side_effect = [summary, local.UpdateError("simulated failure")]
                with self.assertRaisesRegex(local.UpdateError, "本地 SSH IP 尚未修改"):
                    local.execute(args)
                save.assert_not_called()
                self.assertEqual((root / ".envrc").read_text(), original)


if __name__ == "__main__":
    unittest.main()

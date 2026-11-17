"""Offline checks for the deployment script's environment-based configuration."""

import os
import pathlib
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).with_name("sub-store-convert.sh")


class ConvertEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.log = self.root / "curl.log"
        curl = self.root / "curl"
        curl.write_text(
            """#!/usr/bin/env bash
printf '%s\\n' "${!#}" >> "$TEST_CURL_LOG"
if [[ ${1:-} == -sS ]]; then
    printf '%s' "${TEST_HTTP_STATUS:-200}"
else
    printf '{"data":[{"name":"demo"}]}'
fi
""",
            encoding="utf-8",
        )
        curl.chmod(0o755)
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("SUB_STORE_", "VPN_", "TEST_"))
        }
        self.env.update(
            PATH=str(self.root) + os.pathsep + os.environ["PATH"],
            TEST_CURL_LOG=str(self.log),
            SUB_STORE_CONVERT_ENV_FILE=str(self.root / "absent.env"),
            SUB_STORE_API_PREFIX="test-prefix",
            SUB_STORE_PUBLIC_BASE="https://subscriptions.example.com/",
        )

    def run_script(self, choice="0\n"):
        return subprocess.run(
            ["bash", str(SCRIPT)],
            input=choice,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            env=self.env,
            timeout=10,
        )

    def test_default_loopback_api(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            ["http://127.0.0.1:3000/test-prefix/api/utils/env"],
        )

    def test_custom_api_origin_and_public_link(self):
        self.env["SUB_STORE_API_BASE"] = "https://backend.example.com/"
        result = self.run_script("2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            [
                "https://backend.example.com/test-prefix/api/utils/env",
                "https://backend.example.com/test-prefix/api/files",
            ],
        )
        self.assertIn(
            "https://subscriptions.example.com/test-prefix/share/file/demo",
            result.stdout,
        )

    def test_missing_required_variables_fail_before_network(self):
        for name in ("SUB_STORE_API_PREFIX", "SUB_STORE_PUBLIC_BASE"):
            with self.subTest(name=name):
                value = self.env.pop(name)
                result = self.run_script()
                self.env[name] = value
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                self.assertFalse(self.log.exists())

    def test_invalid_prefix_fails_before_network(self):
        self.env["SUB_STORE_API_PREFIX"] = "/invalid-prefix"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SUB_STORE_API_PREFIX", result.stderr)
        self.assertFalse(self.log.exists())

    def test_server_environment_file(self):
        config = self.root / "server.env"
        config.write_text(
            "export SUB_STORE_API_PREFIX=server-prefix\n"
            "export SUB_STORE_PUBLIC_BASE=https://server.example.com\n"
            "export SUB_STORE_API_BASE=http://127.0.0.1:4000\n",
            encoding="utf-8",
        )
        config.chmod(0o600)
        self.env["SUB_STORE_CONVERT_ENV_FILE"] = str(config)
        self.env.pop("SUB_STORE_API_PREFIX")
        self.env.pop("SUB_STORE_PUBLIC_BASE")
        result = self.run_script("2\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "http://127.0.0.1:4000/server-prefix/api/files",
            self.log.read_text(),
        )
        self.assertIn(
            "https://server.example.com/server-prefix/share/file/demo",
            result.stdout,
        )

    def test_service_error_does_not_print_access_prefix(self):
        self.env["TEST_HTTP_STATUS"] = "503"
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("503", result.stderr)
        self.assertNotIn(self.env["SUB_STORE_API_PREFIX"], result.stderr)


if __name__ == "__main__":
    unittest.main()

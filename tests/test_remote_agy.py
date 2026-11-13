"""Synthetic contract tests; no network, CLI installation, credentials or device."""


import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import remote_agy as agy

FIXTURE = json.loads((Path(__file__).parent / "fixtures/agy_quota.json").read_text())


def quota(groups):
    return {"status": "SUCCESS", "command": {"data": {"groups": groups}}}


class ParseTests(unittest.TestCase):
    def test_model_groups_windows_zero_and_timezone(self):
        buckets = agy.parse_quota(FIXTURE)
        self.assertEqual([(b.group, b.window, b.remaining) for b in buckets], [
            ("Synthetic model A", "5h", 0.0),
            ("Synthetic model A", "weekly", .75),
            ("Synthetic model B", "5h", 1.0)])
        self.assertEqual(buckets[1].reset.isoformat(), "2030-01-07T12:00:00+00:00")
        self.assertIsNone(buckets[2].reset)

    def test_unavailable_and_wrong_shapes(self):
        for payload in [None, [], 0, {}, {"usage": {"input_tokens": 123}},
                        quota(None), quota([]), quota([None]),
                        quota([{"disabled": True}]), quota([{"enabled": False}]),
                        quota([{"name": "A", "buckets": None}]),
                        {"status": "SUCCESS", "groups": FIXTURE["command"]["data"]["groups"]}]:
            with self.subTest(payload=payload):
                self.assertIsNone(agy.parse_quota(payload))
        for command in [None, [], "usage", {}, {"data": None}, {"data": []}]:
            self.assertIsNone(agy.parse_quota({"status": "SUCCESS", "command": command}))

    def test_invalid_bucket_values_fail_closed(self):
        for field, values in {
            "remaining_fraction": [True, "0", -1, 2, float("nan"), float("inf"), {}, []],
            "window": [None, "daily", 5],
            "reset_time": [True, {}, "bad", "2030-01-01T12:00:00", ""],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    bucket = {"window": "5h", "remaining_fraction": 0}
                    bucket[field] = value
                    self.assertIsNone(agy.parse_quota(quota([
                        {"name": "A", "buckets": [bucket]}])))

    def test_bad_bucket_does_not_hide_good_ones(self):
        good = {"window": "weekly", "remaining_fraction": .5}
        for bad in [{"window": "daily", "remaining_fraction": .1}, {"window": "5h", "remaining_fraction": 2},
                    {"window": "5h", "remaining_fraction": 0, "reset_time": "bad"}, None]:
            with self.subTest(bad=bad):
                got = agy.parse_quota(quota([{"name": "A", "buckets": [bad, good]},
                                             {"name": "", "buckets": [good]}, None]))
                self.assertEqual(got, [agy.Bucket("A", "weekly", .5, None)])

    def test_missing_null_disabled_are_not_zero(self):
        for bucket in [{}, {"remaining_fraction": None},
                       {"remaining_fraction": 0, "enabled": False},
                       {"remaining_fraction": 0, "disabled": True}]:
            self.assertIsNone(agy.parse_quota(quota([
                {"name": "A", "buckets": [bucket]}])))

    def test_status_required_even_with_valid_groups(self):
        for status in [None, "ERROR", "FAILED", "success", True, {}, []]:
            with self.subTest(status=status):
                self.assertIsNone(agy.parse_quota({**FIXTURE, "status": status}))
        self.assertIsNone(agy.parse_quota({"command": FIXTURE["command"]}))
        self.assertIsNone(agy.parse_quota({**FIXTURE, "error": "synthetic"}))

    def test_sparse_success_and_unrelated_metadata(self):
        minimal = quota([{"name": "Synthetic", "buckets": [
            {"window": "weekly", "remaining_fraction": 0.42}]}])
        expected = [agy.Bucket("Synthetic", "weekly", .42, None)]
        self.assertEqual(agy.parse_quota(minimal), expected)
        self.assertEqual(agy.parse_quota({**minimal, "response": "not JSON",
            "usage": {"remaining_fraction": 0, "total_tokens": 123}}), expected)
        self.assertIsNone(agy.parse_quota({"status": "SUCCESS", "response": json.dumps(minimal),
            "usage": {"total_tokens": 123}}))

    def test_old_camel_case_is_not_quota(self):
        self.assertIsNone(agy.parse_quota(quota([
            {"displayName": "Synthetic", "buckets": [
                {"window": "weekly", "remainingFraction": .42}]}])))


class TransportTests(unittest.TestCase):
    @patch.object(agy, "HOST", "local")
    @patch.object(agy.subprocess, "run")
    def test_local_reads_installed_cli_without_ssh(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, "1.5.5\n"),
                           subprocess.CompletedProcess([], 0, json.dumps(FIXTURE))]
        self.assertEqual(len(agy.agy_quota()), 3)
        version, usage = run.call_args_list
        self.assertEqual(version.args[0][1:], ["--version"])
        self.assertEqual(usage.args[0][1:], ["-p", "/usage", "--output-format", "json"])
        self.assertNotIn("ssh", usage.args[0])
        self.assertEqual(usage.kwargs["stdin"], subprocess.DEVNULL)

    @patch.object(agy, "HOST", "local")
    @patch.object(agy.subprocess, "run")
    def test_local_old_or_unknown_version_never_runs_usage(self, run):
        for version in ("1.1.10", "unknown", "1.5.5-preview"):
            run.reset_mock()
            run.return_value = subprocess.CompletedProcess([], 0, version)
            self.assertIsNone(agy.agy_quota())
            self.assertEqual(run.call_count, 1)

    @patch.object(agy, "HOST", "local")
    @patch.object(agy.subprocess, "run")
    def test_local_authentication_timeout_marks_login_needed(self, run):
        run.side_effect = [subprocess.CompletedProcess([], 0, "1.5.5"),
                           subprocess.TimeoutExpired("agy", 15, output=b"Authentication required")]
        self.assertIsNone(agy.agy_quota())
        self.assertTrue(agy.login_needed)

    @patch.object(agy, "HOST", None)
    @patch.object(agy.subprocess, "run")
    def test_disabled_does_not_connect(self, run):
        self.assertIsNone(agy.agy_quota())
        run.assert_not_called()

    @patch.object(agy, "HOST", "synthetic-host")
    @patch.object(agy.subprocess, "run")
    def test_transport_and_payload(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(FIXTURE))
        self.assertEqual(len(agy.agy_quota()), 3)
        args, kwargs = run.call_args
        self.assertIn("BatchMode=yes", args[0])
        self.assertIn("-T", args[0])
        self.assertEqual(kwargs["timeout"], 90)
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["input"], agy.REMOTE)

    @patch.object(agy, "HOST", "synthetic-host")
    @patch.object(agy.subprocess, "run")
    def test_failures_return_none(self, run):
        for error in [FileNotFoundError(), subprocess.TimeoutExpired("ssh", 90),
                      subprocess.CalledProcessError(255, "ssh"),
                      subprocess.CalledProcessError(1, "ssh", json.dumps(FIXTURE))]:
            run.side_effect = error
            self.assertIsNone(agy.agy_quota())
        run.side_effect = None
        for output in ["not JSON", "", "null", "[]", '{"usage":{"total_tokens":10}}',
                       json.dumps({**FIXTURE, "status": "ERROR"})]:
            run.return_value = subprocess.CompletedProcess([], 0, output)
            self.assertIsNone(agy.agy_quota())


@unittest.skipIf(os.name == 'nt', 'Remote macOS script fixtures require POSIX executables')
class RemoteScriptTests(unittest.TestCase):
    """REMOTE 스크립트를 가짜 agy 실행 파일로 돌려 본다 (네트워크·실제 agy 없이)."""

    def run_remote(self, body: str, version: str = "1.5.4"):
        import os
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            bindir = os.path.join(home, ".local", "bin")
            os.makedirs(bindir)
            fake = os.path.join(bindir, "agy")
            with open(fake, "w") as f:  # -p 로 불리면 표시 파일을 남긴다 (옛 버전에서 /usage 를 안 돌리는지 확인용)
                f.write(f'''#!/bin/sh
if [ "$1" = "--version" ]; then printf '%s' "{version}"; exit 0; fi
[ "$1 $2 $3 $4" = "-p /usage --output-format json" ] || exit 9
touch "$HOME/usage-called"
''' + body)
            os.chmod(fake, 0o755)
            r = subprocess.run([sys.executable, "-"], input=agy.REMOTE, capture_output=True, text=True,
                               timeout=30, env=dict(os.environ, HOME=home))
            return r.returncode, r.stdout, os.path.exists(os.path.join(home, "usage-called"))

    def test_supported_cli_and_noninteractive_path(self):
        payload = json.dumps(FIXTURE)
        for version in ["1.1.11", "agy v1.2.15\n", "1.5.3", "v2.0.0", "agy version 1.6.0\n", "1.5.3 (build abc)\n"]:
            code, output, called = self.run_remote(f"cat <<'JSON'\n{payload}\nJSON\n", version)
            self.assertEqual((code, called), (0, True), version)
            self.assertEqual(json.loads(output), FIXTURE)

    def test_old_unknown_cli_never_runs_usage(self):
        for version in ["1.1.10", "0.9.0", "unknown", "1.2.15-preview", "", "1.2.15.4"]:
            self.assertEqual(self.run_remote("echo '{}'\n", version), (1, "", False), version)

    def test_failure_exits_one_without_output(self):
        payload = json.dumps(FIXTURE)
        self.assertEqual(self.run_remote(f"echo '{payload}'\necho boom >&2\nexit 2\n")[:2], (1, ""))

    def test_missing_agy_exits_one(self):
        import os
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            r = subprocess.run([sys.executable, "-"], input=agy.REMOTE, capture_output=True, text=True, timeout=30,
                               env={"HOME": home, "PATH": "/nonexistent"})
        self.assertEqual((r.returncode, r.stdout), (1, ""))

    def test_login_prompt_exits_fast_with_login_code(self):
        import time
        start = time.time()
        code, output, _ = self.run_remote('echo "Authentication required. Please visit the URL to log in:"\nsleep 30\n')
        self.assertEqual((code, output), (agy.LOGIN_EXIT, ""))
        self.assertLess(time.time() - start, 10)


class LoginStateTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows console login")
    def test_local_login_opens_cli_in_a_console(self):
        with patch.object(agy, "HOST", "local"), patch.object(agy.subprocess, "Popen") as popen:
            self.assertTrue(agy.open_login())
            self.assertEqual(popen.call_args.args[0], [agy.local_cli()])
            self.assertEqual(popen.call_args.kwargs["creationflags"], subprocess.CREATE_NEW_CONSOLE)

    def test_login_exit_code_sets_flag_and_other_errors_clear_it(self):
        import subprocess
        from unittest.mock import patch
        with patch.object(agy, "HOST", "test-host"):
            with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(agy.LOGIN_EXIT, "ssh")):
                self.assertIsNone(agy.agy_quota())
                self.assertTrue(agy.login_needed)
            with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(255, "ssh")):
                self.assertIsNone(agy.agy_quota())
                self.assertFalse(agy.login_needed)

    def test_login_command_quotes_host(self):
        from unittest.mock import patch
        with patch.object(agy, "HOST", "me@host; rm -rf x"):
            self.assertIn("ssh -t 'me@host; rm -rf x' ", agy.login_command())


if __name__ == "__main__":
    unittest.main()

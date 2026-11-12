import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import usage

HOOK = Path(__file__).parents[1] / 'hooks/statusline_hook.py'


class ClaudeStatusTests(unittest.TestCase):
    def test_official_quota_payload_reaches_dashboard_usage(self):
        spec = importlib.util.spec_from_file_location('statusline_hook', HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'claude_status.json'
            payload = {'rate_limits': {'five_hour': {'used_percentage': 31, 'resets_at': 4102444800},
                                       'seven_day': {'used_percentage': 12, 'resets_at': 4102444800}},
                       'workspace': {'current_dir': 'private workspace'}}
            hook.capture(payload, path)
            hook.capture({'rate_limits': None}, path)
            self.assertNotIn('workspace', json.loads(path.read_text(encoding='utf-8')))
            with patch.object(usage, 'CLAUDE_STATUS', str(path)), patch.object(usage, '_recent_files', return_value=[]):
                quotas = usage.claude_usage()
            self.assertEqual((quotas.five_hour.used_percent, quotas.seven_day.used_percent), (31, 12))

    def test_original_statusline_receives_unchanged_stdin(self):
        with tempfile.TemporaryDirectory() as temp:
            echo = Path(temp) / 'echo.py'
            echo.write_text('import sys; print(sys.stdin.read(),end="")', encoding='utf-8')
            previous = {'type': 'command', 'command': f'"{sys.executable}" "{echo}"', 'padding': 2}
            encoded = base64.b64encode(json.dumps(previous).encode()).decode()
            payload = '{"rate_limits": null, "test": "unchanged"}'
            result = subprocess.run([sys.executable, str(HOOK), encoded], input=payload,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, payload)


if __name__ == '__main__':
    unittest.main()

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('install_hooks', Path(__file__).parents[1] / 'scripts/install-hooks.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class HookInstallTests(unittest.TestCase):
    def test_existing_statusline_restored_after_reinstall_and_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            original = {'statusLine': {'type': 'command', 'command': 'existing-tool --flag "x y"', 'padding': 2}}
            path.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(installer, 'CLAUDE_SETTINGS', str(path)):
                installer.claude(True)
                once = json.loads(path.read_text(encoding='utf-8'))
                self.assertIn('statusline_hook.py', once['statusLine']['command'])
                installer.claude(True)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), once)
                installer.claude(False)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), original)

    def test_codex_preserves_existing_notify_and_following_section(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.toml'
            original = 'notify = ["existing-tool", "한글"]\n\n[windows]\nsandbox = "elevated"\n'
            path.write_text(original, encoding='utf-8')
            with patch.object(installer, 'CODEX_CONFIG', str(path)):
                installer.codex(True)
                parsed = tomllib.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(parsed['windows']['sandbox'], 'elevated')
                self.assertEqual(parsed['notify'][-2:], ['existing-tool', '한글'])
                if os.name == 'nt':
                    self.assertEqual(parsed['notify'][0], sys.executable)
                installer.codex(False)
                self.assertEqual(tomllib.loads(path.read_text(encoding='utf-8'))['notify'], ['existing-tool', '한글'])

    def test_claude_preserves_existing_hooks_and_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            existing = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing-tool'}]}]}, 'label': '한글'}
            path.write_text(json.dumps(existing, ensure_ascii=False), encoding='utf-8')
            with patch.object(installer, 'CLAUDE_SETTINGS', str(path)):
                installer.claude(True)
                parsed = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(parsed['label'], '한글')
                self.assertEqual(len(parsed['hooks']['Stop']), 2)
                installer.claude(False)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), existing)


if __name__ == '__main__':
    unittest.main()

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import hook_agents

spec = importlib.util.spec_from_file_location('notification_hook', Path(__file__).parents[1] / 'hooks/agent_hook.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class NotificationTests(unittest.TestCase):
    def test_real_hook_accepts_utf8_payload_on_korean_windows_locale(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {'hook_event_name': 'Stop', 'session_id': 'utf8-test', 'cwd': temp,
                       'last_assistant_message': '한글 요청 완료'}
            env = dict(os.environ, USERPROFILE=temp, HOME=temp, PYTHONUTF8='0', PYTHONIOENCODING='cp949')
            result = subprocess.run([sys.executable, str(Path(hook.__file__)), 'claude'],
                                    input=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                    capture_output=True, env=env, timeout=15)
            self.assertEqual(result.returncode, 0)
            path = Path(temp) / '.cache/d200/agents/claude-code-utf8-test.json'
            self.assertTrue(path.exists(), 'UTF-8 hook input was silently discarded')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'], 'done')

    def test_missing_pid_never_signals_a_posix_process_group(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'working.json'
            path.write_text(json.dumps({'status': 'working', 'updated': time.time()}), encoding='utf-8')
            with patch('glob.glob', return_value=[str(path)]), patch('os.name', 'posix'), \
                 patch('os.kill') as kill, contextlib.redirect_stdout(io.StringIO()):
                exec(hook_agents.SCAN, {})
            kill.assert_not_called()
            self.assertFalse(path.exists())

    def test_new_completion_on_same_thread_realerts_after_acknowledgement(self):
        import dashboard
        from remote_herdr import alert_keys

        for status, count in (('done', 'done'), ('error', 'attention'), ('blocked', 'attention')):
            with self.subTest(status=status):
                record = {'id': 'same-thread', 'agent': 'codex', 'status': status,
                          'project': 'test', 'top': True, '_ssh': None, 'updated': 1}
                with patch.object(hook_agents, '_scan', return_value=[record]):
                    first = hook_agents.state([None])
                with patch.object(hook_agents, '_scan', return_value=[dict(record, updated=2)]):
                    second = hook_agents.state([None])
                self.assertNotEqual(dashboard.signature(first), dashboard.signature(second))

                dash = dashboard.Dashboard.__new__(dashboard.Dashboard)
                dash.acked = alert_keys(first.workspaces[0])
                dash.set_studio(first)
                self.assertEqual(getattr(dash.studio, count), 0)
                dash.set_studio(second)
                self.assertEqual(getattr(dash.studio, count), 1)
                dash.acked |= alert_keys(second.workspaces[0])
                dash.set_studio(second)
                self.assertEqual(getattr(dash.studio, count), 0)

    def test_finished_notifications_survive_process_exit_but_working_records_do_not(self):
        with tempfile.TemporaryDirectory() as temp:
            files = []
            for status, updated in [('done', time.time()), ('error', time.time()),
                                    ('working', time.time()), ('done', 0)]:
                path = Path(temp) / f'{len(files)}.json'
                path.write_text(json.dumps({'pid': 0, 'status': status, 'updated': updated}), encoding='utf-8')
                files.append(str(path))
            output = io.StringIO()
            with patch('glob.glob', return_value=files), contextlib.redirect_stdout(output):
                exec(hook_agents.SCAN, {})
            self.assertEqual([r['status'] for r in json.loads(output.getvalue())], ['done', 'error'])
            self.assertEqual([Path(p).exists() for p in files], [True, True, False, False])

    def test_session_end_keeps_completion_until_dashboard_can_poll_it(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(hook, 'DIR', temp):
            for event in ('Stop', 'SessionEnd'):
                payload = {'hook_event_name': event, 'session_id': 'test', 'cwd': temp}
                with patch.object(hook.sys, 'stdin', io.StringIO(json.dumps(payload))):
                    hook.claude()
            record = json.loads((Path(temp) / 'claude-code-test.json').read_text(encoding='utf-8'))
            self.assertEqual(record['status'], 'done')

    def test_session_end_removes_idle_session(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(hook, 'DIR', temp):
            for event in ('SessionStart', 'SessionEnd'):
                payload = {'hook_event_name': event, 'session_id': 'test', 'cwd': temp}
                with patch.object(hook.sys, 'stdin', io.StringIO(json.dumps(payload))):
                    hook.claude()
            self.assertFalse((Path(temp) / 'claude-code-test.json').exists())


if __name__ == '__main__':
    unittest.main()

import os
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pomodoro


@unittest.skipUnless(os.name == 'nt', 'Windows actions')
class WindowsActionTests(unittest.TestCase):
    def test_hook_uses_agent_pid_instead_of_temporary_shell(self):
        spec = importlib.util.spec_from_file_location('agent_hook', Path(__file__).parents[1] / 'hooks/agent_hook.py')
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        parents = [SimpleNamespace(pid=101, name=lambda: 'cmd.exe'),
                   SimpleNamespace(pid=202, name=lambda: 'codex.exe')]
        with patch('psutil.Process') as process, patch.object(hook, '_ps', return_value=''), \
             patch.object(hook, '_project', return_value='test'):
            process.return_value.parents.return_value = parents
            record = hook._base('codex', 'test-session', 'D:/test')
        self.assertEqual(record['pid'], 202)

    def test_empty_machine_slot_does_not_open_missing_device(self):
        import dashboard
        dash = dashboard.Dashboard.__new__(dashboard.Dashboard)
        dash.device_idx = 0
        with patch.object(dashboard, 'MACHINES', [('This PC', None)]), \
             patch.object(dash, 'render'), patch.object(dash, 'pool', create=True):
            dash.open_device(1)
        self.assertEqual(dash.device_idx, 0)

    def test_timer_completion_uses_windows_sound(self):
        with patch('winsound.MessageBeep') as beep:
            pomodoro.notify_done(25)
        beep.assert_called_once()


if __name__ == '__main__':
    unittest.main()

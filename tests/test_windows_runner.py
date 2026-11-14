import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


class WindowsRunnerTests(unittest.TestCase):
    def test_restarts_after_disconnect_and_appends_logs(self):
        import windows_runner

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dashboard.log').write_text('previous log\n')
            (root / 'dashboard.py').write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "p = Path('attempts')\n"
                "n = int(p.read_text()) + 1 if p.exists() else 1\n"
                "p.write_text(str(n))\n"
                "print(f'attempt {n}')\n"
                "print('device unavailable', file=sys.stderr)\n"
                "sys.exit(1 if n == 1 else 0)\n"
            )
            with patch.object(windows_runner, 'ROOT', root), \
                 patch.object(windows_runner.time, 'sleep', side_effect=[None, KeyboardInterrupt]):
                windows_runner.main()
            self.assertEqual((root / 'attempts').read_text(), '2')
            log = (root / 'dashboard.log').read_text()
            self.assertTrue(log.startswith('previous log\n'))
            self.assertIn('attempt 1', log)
            self.assertIn('attempt 2', log)
            self.assertIn('exited (1)', log)
            self.assertIn('exited (0)', log)
            self.assertEqual((root / 'dashboard-error.log').read_text().count('device unavailable'), 2)

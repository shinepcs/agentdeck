import json
import subprocess
import unittest
from unittest.mock import patch

import machines


class MacConnectionTests(unittest.TestCase):
    def test_remote_probe_preserves_shell_lf_on_windows(self):
        sample = {'ncpu': 12, 'cpu': 25, 'mem': 24 * 1024**3,
                  'mem_free_pct': 70, 'disk_total_kb': 100000,
                  'disk_avail_kb': 25000, 'boot': 1700000000, 'volumes': []}
        with patch.object(machines.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps(sample).encode())
            stat = machines._probe('Mac mini', 'agentdeck-macmini')
        self.assertTrue(stat.online)
        self.assertEqual(stat.mem_gb, 24)
        self.assertEqual(run.call_args.kwargs['input'], machines.PROBE.encode('utf-8'))
        self.assertNotIn('text', run.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()

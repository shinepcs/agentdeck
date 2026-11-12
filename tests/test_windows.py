"""Windows rendering, local stats and safe hook process checks."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import hook_agents
import machines


@unittest.skipUnless(os.name == "nt", "Windows integration checks")
class WindowsTests(unittest.TestCase):
    def test_clock_and_button_render_with_installed_fonts(self):
        from clock import render_clock
        import clock
        from d200 import Button, render_icon
        from PIL import Image

        with patch.dict(clock.CFG, device='d200'):
            self.assertEqual(Image.open(io.BytesIO(render_clock())).size, (458, 196))
        self.assertEqual(Image.open(io.BytesIO(render_icon(Button(title="한글")))).size, (196, 196))

    def test_local_machine_reports_resources(self):
        stat = machines._probe("This PC", None)
        self.assertTrue(stat.online)
        self.assertGreater(stat.mem_gb, 0)
        self.assertGreater(stat.disk_free_gb, 0)
        self.assertGreaterEqual(stat.cpu, 0)
        self.assertLessEqual(stat.cpu, 100)
        self.assertGreaterEqual(stat.uptime_days, 0)

    def test_hook_scan_keeps_live_process_without_signalling_it(self):
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "session.json"
            record.write_text(json.dumps({"pid": os.getpid(), "updated": time.time()}), encoding="utf-8")
            dead = Path(temp) / "dead.json"
            dead.write_text(json.dumps({"pid": 0, "updated": time.time()}), encoding="utf-8")
            stale = Path(temp) / "stale.json"
            stale.write_text(json.dumps({"pid": os.getpid(), "updated": 0}), encoding="utf-8")
            output = io.StringIO()
            with patch("glob.glob", return_value=[str(record), str(dead), str(stale)]), \
                 patch("os.kill", side_effect=AssertionError("must not signal Windows processes")), \
                 contextlib.redirect_stdout(output):
                exec(hook_agents.SCAN, {})
            self.assertEqual(len(json.loads(output.getvalue())), 1)
            self.assertTrue(record.exists())
            self.assertFalse(dead.exists())
            self.assertFalse(stale.exists())

    def test_local_hook_scan_uses_current_python(self):
        with patch.object(hook_agents, "SCAN", 'print("[]")'):
            self.assertEqual(hook_agents._scan(None), [])
        with patch.object(hook_agents.subprocess, "run") as run:
            run.return_value.stdout = "[]"
            hook_agents._scan(None)
            self.assertEqual(run.call_args.args[0][0], sys.executable)


if __name__ == "__main__":
    unittest.main()

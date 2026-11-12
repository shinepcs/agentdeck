"""Keep the Mirabox status strip alive independently of the selected page."""
import contextlib
import io
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import dashboard
from remote_herdr import StudioState


class DashboardStripTests(unittest.TestCase):
    def make_dashboard(self):
        dash = dashboard.Dashboard.__new__(dashboard.Dashboard)
        dash.deck = Mock(disconnected=threading.Event())
        dash.studio = StudioState(True, [])
        dash.llms = []
        return dash

    def test_strip_receives_current_work_and_quota_data(self):
        dash = self.make_dashboard()
        renderer = Mock(return_value=b'png')
        with patch.dict(dashboard.CFG, device='mirabox'), \
             patch.dict(sys.modules, mirabox_strip=SimpleNamespace(render_side_strip=renderer)):
            dash.render_side_strip()
        renderer.assert_called_once_with(dash.studio, dash.llms)
        dash.deck.set_side_strip.assert_called_once_with(b'png')

    def test_d200_does_not_receive_mirabox_commands(self):
        dash = self.make_dashboard()
        with patch.dict(dashboard.CFG, device='d200'):
            dash.render_side_strip()
        dash.deck.set_side_strip.assert_not_called()

    def test_strip_write_error_is_logged_without_stopping_dashboard(self):
        dash = self.make_dashboard()
        dash.deck.set_side_strip.side_effect = OSError('unplugged')
        with patch.dict(dashboard.CFG, device='mirabox'), \
             patch.dict(sys.modules, mirabox_strip=SimpleNamespace(render_side_strip=Mock(return_value=b'png'))), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            dash.render_side_strip()
        self.assertIn('side strip render error: unplugged', output.getvalue())

    def test_strip_refreshes_during_games_and_screensaver(self):
        for page in (dashboard.GAME_PAGE, dashboard.AQUA_PAGE):
            with self.subTest(page=page):
                dash = self.make_dashboard()
                dash.page = page
                dash.brightness_idx = 2
                dash.stop = Mock(is_set=Mock(side_effect=[False, False, True]))
                dash.fetch_now = Mock(wait=Mock(return_value=False))
                dash.pomo = SimpleNamespace(check_finished=lambda: False, state='setup')
                dash.blink_on = False
                dash.games = SimpleNamespace(active=True)
                dash.fetch = Mock()
                dash.render = Mock()
                dash.play_intro = Mock()
                dash.render_side_strip = Mock()
                with patch.object(dashboard, 'REFRESH_SEC', 1), \
                     patch.object(dashboard.updater, 'start_background'), \
                     contextlib.redirect_stdout(io.StringIO()):
                    dash.run()
                self.assertEqual(dash.render_side_strip.call_count, 3)
                dash.deck.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()

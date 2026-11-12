import io
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

import clock


class MiraboxPanelTests(unittest.TestCase):
    def test_information_panels_are_native_two_key_images(self):
        index = SimpleNamespace(name='KOSPI', price='2,700.00', change=1.25, status='OPEN')
        calls = [lambda: clock.render_clock(datetime(2026, 11, 12, 12, 34), [('작업 1', '#7aa2f7')]),
                 lambda: clock.render_timer(1500, 'running', 1800000000),
                 lambda: clock.render_worktree_summary(None),
                 lambda: clock.render_message('알림', ['첫 번째 안내', '두 번째 안내']),
                 lambda: clock.render_market([index, index], (100, 20), '코스피')]
        with patch.dict(clock.CFG, device='mirabox'):
            for render in calls:
                self.assertEqual(Image.open(io.BytesIO(render())).size, (200, 100))

    def test_legacy_d200_panel_stays_original_size(self):
        with patch.dict(clock.CFG, device='d200'):
            self.assertEqual(Image.open(io.BytesIO(clock.render_clock())).size, (458, 196))

    def test_worktree_message_keeps_double_hold_and_delete_condition(self):
        import mirabox_render
        lines = ['짧게: Herdr 에서 열기', '길게 2번: 정리 가능 → 삭제',
                 '길게 2번: 그 외 → 총괄에 정리 요청']
        with patch.dict(clock.CFG, device='mirabox'), patch.object(mirabox_render, 'render_panel') as render:
            clock.render_message('워크트리', lines)
        left, right = render.call_args.args
        text = ' '.join((left.header, left.title, left.sub, right.header, right.title, right.sub))
        for phrase in ('짧게', 'Herdr', '길게 2번', '정리 가능', '삭제', '그외 요청'):
            self.assertIn(phrase, text)


if __name__ == '__main__':
    unittest.main()

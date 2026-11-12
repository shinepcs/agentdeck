import importlib
import importlib.util
import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from PIL import Image, ImageDraw

from pages import LLM, Limit
from remote_herdr import StudioState, Workspace


class SideStripTests(unittest.TestCase):
    now = datetime(2026, 11, 12, 14, 32, 30, tzinfo=timezone(timedelta(hours=9)))

    def render(self, studio=None, llms=None, lang='ko', now=None):
        self.assertIsNotNone(importlib.util.find_spec('mirabox_strip'), 'side strip renderer is missing')
        module = importlib.import_module('mirabox_strip')
        labels = []
        original = ImageDraw.ImageDraw.text
        original_draw = ImageDraw.Draw

        def capture_draw(image, *args, **kwargs):
            self.source_image = image
            return original_draw(image, *args, **kwargs)

        def record(draw, xy, text, *args, **kwargs):
            labels.append((text, kwargs['font'].size,
                           draw.textbbox(xy, text, font=kwargs['font'], anchor=kwargs.get('anchor')),
                           kwargs['fill']))
            return original(draw, xy, text, *args, **kwargs)

        with patch('i18n.LANG', lang), patch.object(ImageDraw.ImageDraw, 'text', record), \
             patch.object(ImageDraw, 'Draw', capture_draw):
            png = module.render_side_strip(studio or StudioState(True, []), llms or [], now or self.now)
        return Image.open(io.BytesIO(png)), labels

    def test_native_size_and_source_text_before_safe_area_scaling(self):
        image, labels = self.render()
        self.assertEqual(image.size, (96, 288))
        self.assertIn('14:32', [label[0] for label in labels])
        self.assertTrue(all(size >= 16 for _, size, _, _ in labels))

    def test_time_date_weekday_and_large_statuses_are_always_visible(self):
        studio = StudioState(True, [Workspace('example', working=3, attention=1, done=16, idle=4)])
        previous = None
        for second in (30, 35, 40):
            image, labels = self.render(studio, now=self.now.replace(second=second))
            self.assertEqual([entry[0] for entry in labels[:3]], ['14:32', '11/12', '목요일'])
            self.assertGreater(labels[0][1], 22)
            self.assertGreater(labels[1][1], 20)
            self.assertGreater(labels[2][1], 20)
            self.assertEqual([entry[0] for entry in labels[3:7]],
                             ['작업 3', '확인 1', '완료 16', '대기 4'])
            self.assertTrue(all(entry[1] >= 24 for entry in labels[3:7]))
            if previous is not None:
                self.assertEqual(image.tobytes(), previous)
            previous = image.tobytes()

    def test_final_pixels_stay_inside_each_panels_safe_area(self):
        from PIL import ImageChops
        from mirabox_render import BG

        studio = StudioState(True, [Workspace('many', working=123, attention=99, done=1000, idle=8)])
        llms = [LLM('CLAUDE', '#d97757', Limit(1, None, timedelta(hours=5)),
                    Limit(0, None, timedelta(days=7))),
                LLM('CODEX', '#10a37f', Limit(None, None, timedelta(hours=5)),
                    Limit(.99, None, timedelta(days=7)))]
        for lang in ('ko', 'en'):
            for state, models in ((studio, llms), (StudioState(False, []), []),
                                  (studio, [LLM('CLAUDE', '#d97757', login=True)])):
                image, _ = self.render(state, models, lang=lang)
                for panel in range(3):
                    with self.subTest(lang=lang, panel=panel, online=state.online):
                        tile = image.crop((0, panel * 96, 96, (panel + 1) * 96))
                        safe = Image.new('RGB', (96, 96), BG)
                        safe.paste(tile.crop((16, 16, 80, 80)), (16, 16))
                        self.assertIsNone(ImageChops.difference(tile, safe).getbbox())
                        self.assertIsNotNone(ImageChops.difference(
                            tile, Image.new('RGB', (96, 96), BG)).getbbox())

    def test_all_four_work_states_are_visible(self):
        studio = StudioState(True, [Workspace('example', working=3, attention=1, done=2, idle=4)])
        _, labels = self.render(studio)
        texts = [label[0] for label in labels]
        for value in ('작업 3', '확인 1', '완료 2', '대기 4'):
            self.assertIn(value, texts)
        status_labels = labels[3:7]
        self.assertTrue(all(size >= 24 for _, size, _, _ in status_labels))
        for previous, current in zip(status_labels, status_labels[1:]):
            self.assertLess(previous[2][3], current[2][1])

    def test_date_is_larger_and_separated_from_inset_status_rows(self):
        studio = StudioState(True, [Workspace('example', working=3, attention=1, done=16, idle=4)])
        _, labels = self.render(studio, now=self.now.replace(second=35))
        date = next(entry for entry in labels if entry[0] == '11/12')
        self.assertGreaterEqual(date[1], 28)
        counts = labels[3:7]
        self.assertGreaterEqual(min(entry[2][1] for entry in counts) - date[2][3], 1)
        for _, size, (left, top, right, bottom), _ in counts:
            self.assertGreaterEqual(size, 24)
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(right, 96)
            self.assertGreaterEqual(top, 96)
            self.assertLessEqual(bottom, 192)

    def test_zero_quota_is_distinct_from_unknown_and_values_are_remaining(self):
        llms = [LLM('CLAUDE', '#d97757', Limit(0, None, timedelta(hours=5)),
                    Limit(None, None, timedelta(days=7))),
                LLM('CODEX', '#10a37f', Limit(.82, None, timedelta(hours=5)),
                    Limit(.36, None, timedelta(days=7)))]
        _, labels = self.render(llms=llms)
        texts = [label[0] for label in labels]
        for value in ('CLAUDE', 'CODEX', '0%', '—', '82%', '36%', '5H', '7D'):
            self.assertIn(value, texts)
        self.assertEqual(llms[1].five.remaining, .82)

    def test_offline_loading_and_login_are_explicit(self):
        _, labels = self.render(StudioState(False, []), now=self.now.replace(second=35))
        texts = [label[0] for label in labels]
        for value in ('14:32', '11/12', '목요일', '작업 —', '확인 —', '완료 —', '대기 —'):
            self.assertIn(value, texts)
        self.assertIn('조회 중', texts)
        self.assertIn('—', texts)
        _, labels = self.render(llms=[LLM('CLAUDE', '#d97757', login=True)])
        self.assertIn('로그인', [label[0] for label in labels])

    def test_text_bounds_and_contrast_hold_for_large_values_and_all_states(self):
        from mirabox_render import contrast
        studio = StudioState(True, [Workspace('many', working=123, attention=99, done=1000, idle=8)])
        llms = [LLM('CLAUDE', '#d97757', Limit(1, None, timedelta(hours=5)),
                    Limit(.15, None, timedelta(days=7))),
                LLM('CODEX', '#10a37f', Limit(.4, None, timedelta(hours=5)),
                    Limit(-.2, None, timedelta(days=7)))]
        image, labels = self.render(studio, llms)
        for text, _, (left, top, right, bottom), fg in labels:
            with self.subTest(text=text):
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(right, 96)
                self.assertLessEqual(bottom, 288)
                middle = (top + bottom) // 2
                background = self.source_image.getpixel((0, min(287, middle)))
                self.assertGreaterEqual(contrast(fg, background), 7)

    def test_text_stays_within_one_physical_96_pixel_zone_in_both_languages(self):
        studio = StudioState(True, [Workspace('many', working=123, attention=99, done=1000, idle=88)])
        for lang in ('ko', 'en'):
            for state, models in ((studio, [LLM('CLAUDE', '#d97757', login=True)]),
                                  (StudioState(False, []), [])):
                _, labels = self.render(state, models, lang=lang)
                for text, _, (left, top, right, bottom), _ in labels:
                    with self.subTest(lang=lang, text=text):
                        self.assertGreaterEqual(left, 0)
                        self.assertLessEqual(right, 96)
                        self.assertEqual(top // 96, (bottom - 1) // 96)

    def test_each_provider_and_its_two_limits_stay_on_one_panel(self):
        llms = [LLM('CLAUDE', '#d97757', Limit(.82, None, timedelta(hours=5)),
                    Limit(.36, None, timedelta(days=7))),
                LLM('CODEX', '#10a37f', Limit(.12, None, timedelta(hours=5)),
                    Limit(1, None, timedelta(days=7)))]
        _, labels = self.render(llms=llms)
        for offset, expected in ((192, ('CLAUDE', '5H', '82%', '7D', '36%')),
                                 (240, ('CODEX', '5H', '12%', '7D', '100%'))):
            texts = [value for value, _, (_, top, _, bottom), _ in labels
                     if top >= offset and bottom <= offset + 48]
            self.assertEqual(texts, list(expected))

    def test_quota_text_is_larger_and_rows_do_not_overlap(self):
        limit = Limit(1, None, timedelta(hours=5))
        _, labels = self.render(llms=[LLM('CLAUDE', '#d97757', limit, limit),
                                     LLM('CODEX', '#10a37f', limit, limit)])
        for offset in (192, 240):
            entries = [entry for entry in labels
                       if offset <= entry[2][1] and entry[2][3] <= offset + 48]
            self.assertEqual(len(entries), 5)
            self.assertGreaterEqual(entries[0][1], 20)
            for index in (1, 3):
                label, value = entries[index:index + 2]
                self.assertGreaterEqual(label[1], 20)
                self.assertGreaterEqual(value[1], 22)
                self.assertGreaterEqual(value[2][0] - label[2][2], 6)
            self.assertLess(entries[0][2][3], min(e[2][1] for e in entries[1:3]))
            self.assertLess(max(e[2][3] for e in entries[1:3]),
                            min(e[2][1] for e in entries[3:5]))

    def test_nonfinite_quota_is_unknown_instead_of_full(self):
        llms = [LLM('CLAUDE', '#d97757', Limit(float('nan'), None, timedelta(hours=5)),
                    Limit(float('inf'), None, timedelta(days=7)))]
        _, labels = self.render(llms=llms)
        texts = [label[0] for label in labels]
        self.assertNotIn('100%', texts)
        self.assertNotIn('nan%', texts)

    def test_full_status_names_and_large_counts_fit_centered_rows_in_both_languages(self):
        studio = StudioState(True, [Workspace('many', working=123, attention=123, done=123, idle=123)])
        for lang, names in (('ko', ('작업', '확인', '완료', '대기')),
                            ('en', ('RUN', 'ASK', 'DONE', 'IDLE'))):
            _, labels = self.render(studio, lang=lang)
            counts = [entry for entry in labels if entry[0].endswith(' 99+')]
            self.assertEqual([entry[0] for entry in counts], [f'{name} 99+' for name in names])
            for _, _, (left, top, right, bottom), _ in counts:
                self.assertGreaterEqual(left, 0)
                self.assertLessEqual(right, 96)
                self.assertGreaterEqual(top, 96)
                self.assertLessEqual(bottom, 192)
            self.assertTrue(all(entry[1] >= (22 if lang == 'ko' else 18) for entry in counts))


if __name__ == '__main__':
    unittest.main()

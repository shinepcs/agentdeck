import io
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from d200 import Button


@patch('i18n.LANG', 'ko')
class ReadabilityTests(unittest.TestCase):
    def test_filled_tile_keeps_text_contrast(self):
        import mirabox_render as render
        original = ImageDraw.ImageDraw.text
        drawn = []
        def record(draw, xy, text, *args, **kwargs):
            if text == '25분':
                drawn.append((kwargs['fill'], draw.textbbox(xy, text, font=kwargs['font'], anchor=kwargs['anchor'])))
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, 'text', record):
            png = render.render_icon(Button(title='25분', bg='#16161e', fg='#16161e',
                                             fill=1, fill_color='#f7768e'))
        color, (left, top, _, _) = drawn[0]
        image = Image.open(io.BytesIO(png))
        self.assertGreaterEqual(render.contrast(color, image.getpixel((left - 1, top - 1))), 7)

    def test_destructive_confirmation_survives_long_project_header(self):
        import mirabox_render as render
        original = ImageDraw.ImageDraw.text
        labels = []
        def record(draw, xy, text, *args, **kwargs):
            labels.append(text)
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, 'text', record):
            render.render_icon(Button(header='GuardianRenewal', raw_header=True, title='삭제?',
                                      sub='길게 한 번 더', bg='#f7768e', fg='#16161e'))
        self.assertIn('다시 길게', ' '.join(labels))

    def test_update_pages_do_not_lose_every_fourth_item(self):
        import intro
        notes = [f'update {index}' for index in range(7)]
        with patch.dict(intro.CFG, device='mirabox'), patch('clock.render_message') as render:
            for page in range(3):
                intro.home_wide([], False, notes, len(notes), page)
        shown = [line for call in render.call_args_list for line in call.args[1]]
        self.assertTrue(all(note in shown for note in notes))

    def test_home_shortcut_is_native_size(self):
        import intro
        with patch.dict('config.CFG', {'device': 'mirabox'}):
            png = intro.shortcut_tile('작업 현황', '에이전트', 'robot', '#565f89')
        self.assertEqual(Image.open(io.BytesIO(png)).size, (100, 100))

    def test_navigation_preserves_brightness_and_long_press_hint(self):
        import mirabox_render as render
        original = ImageDraw.ImageDraw.text
        labels = []
        def record(draw, xy, text, *args, **kwargs):
            labels.append(text)
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, 'text', record):
            render.render_icon(Button(header='3/8 페이지', title='홈', sub='길게: 밝기 80'))
        joined = ' '.join(labels)
        self.assertIn('길게:', joined)
        self.assertIn('밝기', joined)
        self.assertIn('80', joined)

    def test_native_key_uses_bold_fonts_at_least_16_pixels(self):
        import mirabox_render as render
        original = ImageDraw.ImageDraw.text
        drawn = []

        def record(draw, xy, text, *args, **kwargs):
            drawn.append((text, kwargs['font'].size, kwargs['fill']))
            return original(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, 'text', record):
            png = render.render_icon(Button(header='GuardianRenewal · macproui-Macmini', raw_header=True,
                                             title='작업 1', sub='C1 · 실행 1', accent='#565f89'))
        self.assertEqual(Image.open(io.BytesIO(png)).size, (100, 100))
        self.assertTrue(drawn)
        self.assertTrue(all(size >= 16 for _, size, _ in drawn))
        self.assertTrue(all(render.contrast(color, render.BG) >= 7 for _, _, color in drawn))

    def test_long_labels_wrap_and_ellipsize_without_shrinking(self):
        import mirabox_render as render
        font = render.font()
        lines = render.wrap_text('GuardianRenewal · macproui-Macmini', font, 88, 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith('…'))
        draw = ImageDraw.Draw(Image.new('RGB', (100, 100)))
        self.assertTrue(all(draw.textlength(line, font=font) <= 88 for line in lines))
        self.assertGreaterEqual(font.size, 16)

    def test_alert_background_keeps_dark_text_readable(self):
        import mirabox_render as render
        png = render.render_icon(Button(title='완료 1', bg='#9ece6a', fg='#16161e', accent='#16161e'))
        image = Image.open(io.BytesIO(png))
        self.assertGreaterEqual(render.contrast('#05080d', image.getpixel((50, 99))), 7)

    def test_bars_show_each_value_as_text_including_unknown(self):
        import mirabox_render as render
        original = ImageDraw.ImageDraw.text
        labels = []
        def record(draw, xy, text, *args, **kwargs):
            labels.append(text)
            return original(draw, xy, text, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, 'text', record):
            render.render_icon(Button(header='CLAUDE', title='31%',
                                      bars=[('5H', .31, '#565f89'), ('주간', None, '#565f89'),
                                            ('디스크', 1, '#565f89', '100%')]))
        self.assertIn('31%', labels)
        self.assertIn('-', labels)
        self.assertIn('DISK', labels)
        self.assertIn('100%', labels)


if __name__ == '__main__':
    unittest.main()

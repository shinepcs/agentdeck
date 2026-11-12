"""Readable text at the HSV293S's actual 100px key resolution."""
from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

from d200 import FONT_PATH, Button
from i18n import t, tr

SIZE, MIN_FONT = 100, 16
BG = '#05080d'
WHITE = '#ffffff'
_bold = Path(FONT_PATH).with_name('malgunbd.ttf')
FONT = str(_bold) if os.name == 'nt' and _bold.exists() else FONT_PATH


@lru_cache(maxsize=32)
def font(size: int = MIN_FONT) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, max(MIN_FONT, size))


def _rgb(color) -> tuple:
    return ImageColor.getrgb(color) if isinstance(color, str) else tuple(color[:3])


def _luminance(color) -> float:
    channels = [c / 255 for c in _rgb(color)]
    return sum(weight * (c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4)
               for c, weight in zip(channels, (.2126, .7152, .0722)))


def contrast(foreground, background) -> float:
    a, b = sorted((_luminance(foreground), _luminance(background)))
    return (b + .05) / (a + .05)


def readable_color(color, bg=BG) -> tuple:
    rgb = _rgb(color or WHITE)
    target = _rgb(WHITE if _luminance(bg) < .3 else BG)
    for amount in (0, .25, .5, .75, 1):
        result = tuple(round(c + (t - c) * amount) for c, t in zip(rgb, target))
        if contrast(result, bg) >= 7:
            return result
    return target


def fit_text(text: str, fnt, width: int) -> str:
    text = text.replace('\n', ' ').strip()
    if fnt.getlength(text) <= width:
        return text
    while text and fnt.getlength(text + '…') > width:
        text = text[:-1]
    return text.rstrip() + '…'


def wrap_text(text: str, fnt, width: int, max_lines: int = 2) -> list[str]:
    remaining = text.replace('\n', ' ').strip()
    lines = []
    while remaining and len(lines) < max_lines:
        if len(lines) == max_lines - 1 or fnt.getlength(remaining) <= width:
            lines.append(fit_text(remaining, fnt, width))
            break
        end = 1
        while end < len(remaining) and fnt.getlength(remaining[:end + 1]) <= width:
            end += 1
        space = remaining.rfind(' ', 0, end + 1)
        if space > end // 2:
            end = space
        lines.append(remaining[:end].rstrip())
        remaining = remaining[end:].lstrip()
    return lines


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def render_icon(button: Button) -> bytes:
    if button.image is not None:
        return button.image
    alert = _luminance(button.fg) < .2 and _luminance(button.bg) > .2
    bg = tuple(round(c * .4 + 255 * .6) for c in _rgb(button.bg)) if alert else _rgb(BG)
    image = Image.new('RGB', (SIZE, SIZE), bg)
    draw = ImageDraw.Draw(image)
    fg = readable_color(button.fg, bg)
    accent = readable_color(button.accent or WHITE, bg)
    if button.fill is not None and button.fill > 0:
        draw.rectangle((0, round(SIZE * (1 - min(1, button.fill))), SIZE, SIZE), fill=button.fill_color)
    if button.border:
        draw.rounded_rectangle((1, 1, 98, 98), radius=6, outline=readable_color(button.border, bg), width=2)

    def line(text, y, size=MIN_FONT, color=fg, anchor='mt', x=50):
        fnt = font(size)
        text = fit_text(text, fnt, 88)
        if text and button.fill is not None and button.fill > 0:
            left, top, right, bottom = draw.textbbox((x, y), text, font=fnt, anchor=anchor)
            draw.rectangle((left - 1, top - 1, right + 1, bottom + 1), fill=BG)
            color = readable_color(color, BG)
        draw.text((x, y), text, font=fnt, fill=color, anchor=anchor)

    header = button.header if button.raw_header else tr(button.header)
    if button.bars:
        line(header, 4, color=readable_color(button.header_fg or button.accent or WHITE, bg))
        for index, bar in enumerate(button.bars[:3]):
            label, ratio, color = bar[:3]
            value = tr(bar[3]) if len(bar) > 3 else ('-' if ratio is None else f'{ratio * 100:.0f}%')
            y = 25 + index * 24
            fnt = font()
            label = {'메모리': 'RAM', 'Memory': 'RAM', '디스크': 'DISK', 'Disk': 'DISK'}.get(tr(label), tr(label))
            label = fit_text(label, fnt, max(20, 84 - fnt.getlength(value)))
            line(label, y, anchor='lt', x=6)
            line(value, y, anchor='rt', x=94)
            draw.rectangle((6, y + 18, 93, y + 21), fill='#354153')
            if ratio is not None and ratio > 0:
                draw.rectangle((6, y + 18, 6 + round(87 * min(1, ratio)), y + 21), fill=readable_color(color, bg))
        if len(button.bars) <= 2:
            line(tr(button.sub), 80)
    else:
        headers = wrap_text(header, font(), 88, 2)
        sub = t('다시 길게', 'Hold again') if button.sub == '길게 한 번 더' else tr(button.sub)
        subs = wrap_text(sub, font(), 88, 2 if len(headers) <= 1 else 1)
        for index, text in enumerate(headers):
            line(text, 5 + index * 18, color=readable_color(button.header_fg or button.accent or WHITE, bg))
        title = tr(button.title)
        size = 28
        while size > MIN_FONT and font(size).getlength(title) > 88:
            size -= 2
        line(title, 31 if len(subs) == 2 else 43, size)
        for index, text in enumerate(subs):
            line(text, 62 + index * 18 if len(subs) == 2 else 78)
        if button.ratio is not None:
            draw.rectangle((6, 96, 93, 99), fill='#354153')
            if button.ratio > 0:
                draw.rectangle((6, 96, 6 + round(87 * min(1, button.ratio)), 99), fill=accent)
    return _png(image)


def render_panel(left: Button, right: Button) -> bytes:
    image = Image.new('RGB', (200, SIZE), BG)
    for index, button in enumerate((left, right)):
        with Image.open(io.BytesIO(render_icon(button))) as key:
            image.paste(key.resize((SIZE, SIZE), Image.Resampling.LANCZOS), (index * SIZE, 0))
    return _png(image)

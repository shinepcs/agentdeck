"""Clock, agent states and quotas for three independent native 96×96 panels."""
from __future__ import annotations

import io
import math
from datetime import datetime
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from i18n import t
from mirabox_render import BG, font, readable_color

STATUS_FONT = font(24)

if TYPE_CHECKING:
    from pages import LLM
    from remote_herdr import StudioState


def render_side_strip(studio: StudioState, llms: list[LLM], now: datetime | None = None) -> bytes:
    now = now or datetime.now().astimezone()
    image = Image.new('RGB', (96, 288), BG)
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=16, color='#ffffff', bg=BG, anchor='lm'):
        draw.text((x, y), value, font=font(size), fill=readable_color(color, bg), anchor=anchor)

    weekday = t('월화수목금토일'[now.weekday()] + '요일',
                ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[now.weekday()])
    text(48, 15, now.strftime('%H:%M'), 34, anchor='mm')
    text(48, 48, now.strftime('%m/%d'), 28, anchor='mm')
    text(48, 80, weekday, 24, anchor='mm')

    states = (
        (t('작업', 'RUN'), studio.working, '#193b6b', '#cce2ff'),
        (t('확인', 'ASK'), studio.attention, '#ffcc66', BG),
        (t('완료', 'DONE'), studio.done, '#99e2a1', BG),
        (t('대기', 'IDLE'), sum(w.idle for w in studio.workspaces), '#293544', '#ffffff'),
    )
    for index, (label, count, active_bg, active_fg) in enumerate(states):
        y = 106 + index * 24
        bg = active_bg if studio.online and count else '#101923'
        fg = readable_color(active_fg if studio.online and count else '#bacde0', bg)
        draw.rectangle((0, y - 10, 95, y + 13), fill=bg)
        value = ('99+' if count > 99 else str(max(0, count))) if studio.online else '—'
        content = f'{label} {value}'
        status_font = STATUS_FONT
        for size in (22, 20, 18):
            if status_font.getlength(content) <= 94:
                break
            status_font = font(size)
        draw.text((48, y), content, font=status_font, fill=fg, anchor='mm')

    providers = {m.name.upper(): m for m in llms}
    # shortcut: the narrow always-visible strip shows Claude/Codex; other providers remain on the quota page.
    for index, (name, color, header_bg) in enumerate((('CLAUDE', '#efae91', '#281c18'),
                                                     ('CODEX', '#8fe2c0', '#14271f'))):
        y = 192 + index * 48
        model = providers.get(name)
        draw.rectangle((0, y, 95, y + 13), fill=header_bg)
        text(48, y + 5, name, 20, color=color, bg=header_bg, anchor='mm')
        if model is None or model.login:
            text(48, y + 23, t('로그인', 'LOGIN') if model and model.login else t('조회 중', 'LOADING'),
                 color='#ffcc66' if model else '#bacde0', anchor='mm')
            text(48, y + 39, t('필요', 'NEEDED') if model and model.login else '—', anchor='mm')
            continue
        for row, (label, limit) in enumerate((('5H', model.five), ('7D', model.week))):
            top = y + 14 + row * 17
            remaining = limit.remaining if limit else None
            remaining = max(0.0, min(1.0, remaining)) if remaining is not None and math.isfinite(remaining) else None
            bg = '#3b1820' if remaining is not None and remaining <= .15 else BG
            color = '#ffb0bb' if remaining is not None and remaining <= .15 else \
                    '#ffda88' if remaining is not None and remaining <= .4 else '#a2e8b3'
            draw.rectangle((0, top, 95, top + 16), fill=bg)
            text(2, top + 8, label, 20, color='#c4d3e2', bg=bg)
            value = '—' if remaining is None else f'{remaining * 100:.0f}%'
            text(94, top + 8, value, 22, color='#bacde0' if remaining is None else color, bg=bg, anchor='rm')

    # The device bezel hides the panel edges; keep the entire layout inside a 16px inset.
    safe = Image.new('RGB', image.size, BG)
    for top in (0, 96, 192):
        panel = image.crop((0, top, 96, top + 96)).resize((64, 64), Image.Resampling.LANCZOS)
        safe.paste(panel, (16, top + 16))
    buffer = io.BytesIO()
    safe.save(buffer, 'PNG')
    return buffer.getvalue()

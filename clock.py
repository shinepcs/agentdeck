"""오른쪽 아래 넓은 칸(458x196)에 들어갈 커스텀 시계 이미지."""

from __future__ import annotations

import io
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from i18n import tr


class _Draw(ImageDraw.ImageDraw):
    """글자를 그리거나 잴 때 화면 언어로 바꾸는 ImageDraw."""

    def text(self, xy, text, *args, **kwargs):
        return super().text(xy, tr(text), *args, **kwargs)

    def textlength(self, text, *args, **kwargs):
        return super().textlength(tr(text), *args, **kwargs)

W, H = 458, 196
SF_ROUNDED = "/System/Library/Fonts/SFNSRounded.ttf"
KR = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
EMOJI_FONT = "/System/Library/Fonts/Apple Color Emoji.ttc"
if os.name == "nt":
    _fonts = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    SF_ROUNDED = os.path.join(_fonts, "segoeuib.ttf")
    KR = os.path.join(_fonts, "malgun.ttf")
    EMOJI_FONT = os.path.join(_fonts, "seguiemj.ttf")
WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def _sf(size: int, weight: bytes = b"Semibold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(SF_ROUNDED, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def _kr(size: int, index: int) -> ImageFont.FreeTypeFont:
    # index: 0 Regular, 2 Medium, 4 SemiBold, 6 Bold, 8 Light
    return ImageFont.truetype(KR, size, index=0 if os.name == "nt" else index)


def render_clock(now: datetime | None = None, status: list[tuple[str, str]] | None = None) -> bytes:
    """시:분 + 요일/날짜 + 하단 상태 칩 + 하루 진행 막대.

    status: [(텍스트, 색), ...] 하단에 점 칩으로 표시
    """
    now = now or datetime.now()
    img = Image.new("RGB", (W, H), "#0d0e14")
    d = _Draw(img)

    # 은은한 세로 그라데이션 배경
    top, bottom = (22, 24, 36), (12, 13, 19)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))

    # 시간
    hh, mm = now.strftime("%H"), now.strftime("%M")
    big = _sf(104, b"Semibold")
    x, y = 24, 18
    d.text((x, y), hh, font=big, fill="#e6e9f5")
    x += d.textlength(hh, font=big)
    # 콜론은 강조색으로, 살짝 위로
    colon = _sf(92, b"Medium")
    d.text((x + 2, y + 2), ":", font=colon, fill="#7aa2f7")
    x += d.textlength(":", font=colon) + 4
    d.text((x, y), mm, font=big, fill="#e6e9f5")
    time_right = x + d.textlength(mm, font=big)

    # 요일 / 날짜 (오른쪽 정렬)
    rx = W - 22
    d.text((rx, 40), WEEKDAYS[now.weekday()], font=_kr(30, 6), fill="#7aa2f7", anchor="ra")
    d.text((rx, 80), f"{now.month}월 {now.day}일", font=_kr(26, 2), fill="#a9b1d6", anchor="ra")
    # 구분선 (시간과 날짜 사이)
    right_w = max(d.textlength(f"{now.month}월 {now.day}일", font=_kr(26, 2)),
                  d.textlength(WEEKDAYS[now.weekday()], font=_kr(30, 6)))
    sep_x = int((time_right + rx - right_w) / 2) - 4
    d.line([(sep_x, 42), (sep_x, 110)], fill="#2a2e42", width=2)

    # 하단 상태 칩
    cx, cy = 26, 152
    chip = _kr(20, 2)
    for text, color in status or []:
        d.ellipse((cx, cy - 5, cx + 10, cy + 5), fill=color)
        d.text((cx + 16, cy), text, font=chip, fill="#c0caf5", anchor="lm")
        cx += 16 + d.textlength(text, font=chip) + 22

    # 하루 진행 막대 (맨 아래)
    frac = (now.hour * 60 + now.minute) / 1440
    d.rectangle((0, H - 6, W, H), fill="#1f2233")
    d.rectangle((0, H - 6, int(W * frac), H), fill="#3d59a1")

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


if __name__ == "__main__":
    import sys

    open(sys.argv[1], "wb").write(render_clock(status=[("작업 3", "#7aa2f7"), ("확인 0", "#565f89"), ("추천 AGY", "#9ece6a")]))


def render_timer(remaining: float, state: str, end_at: float | None, color: str = "#f7768e") -> bytes:
    """뽀모도로용 넓은 칸: 남은 mm:ss 크게 + 상태 + 끝나는 시각."""
    img = Image.new("RGB", (W, H), "#0d0e14")
    d = _Draw(img)
    m, s = divmod(int(round(remaining)), 60)
    d.text((24, 98), f"{m:02d}:{s:02d}", font=_sf(112, b"Semibold"), fill="#e6e9f5", anchor="lm")
    label = {"running": "집중 중", "paused": "일시정지", "done": "완료!", "setup": "시간 선택"}.get(state, "")
    rx = W - 22
    d.text((rx, 62), label, font=_kr(30, 6), fill=color, anchor="ra")
    if state == "running" and end_at:
        d.text((rx, 104), datetime.fromtimestamp(end_at).strftime("%H:%M 종료"), font=_kr(24, 2), fill="#a9b1d6", anchor="ra")
    elif state == "paused":
        d.text((rx, 104), "아무 칸: 계속", font=_kr(22, 2), fill="#a9b1d6", anchor="ra")
    elif state == "done":
        d.text((rx, 104), "누르면 닫기", font=_kr(22, 2), fill="#a9b1d6", anchor="ra")
    d.text((24, 170), {"running": "짧게: 일시정지 · 길게: 취소", "paused": "'취소' 칸 또는 길게: 종료"}.get(state, ""),
           font=_kr(19, 2), fill="#565f89", anchor="lm")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


WT_COLORS = {"방치": "#e0af68", "정리 가능": "#9ece6a", "오래됨": "#ff9e64", "작업": "#7aa2f7", "정상": "#565f89"}


def render_worktree_summary(items, hint: str = "눌러서 워크트리 보기") -> bytes:
    """작업 현황 페이지의 넓은 칸: 워크트리 수 + 상태별 칩."""
    img = Image.new("RGB", (W, H), "#0d0e14")
    d = _Draw(img)
    d.text((24, 30), "워크트리", font=_kr(26, 6), fill="#bb9af7", anchor="lm")
    if items is None:
        d.text((24, 100), "연결 안 됨", font=_kr(40, 4), fill="#f7768e", anchor="lm")
    else:
        d.text((24, 100), str(len(items)), font=_sf(96, b"Semibold"), fill="#e6e9f5", anchor="lm")
        counts: dict[str, int] = {}
        for w in items:
            counts[w.state] = counts.get(w.state, 0) + 1
        y = 46
        for st in ("방치", "정리 가능", "오래됨", "작업"):
            if counts.get(st):
                d.ellipse((190, y - 6, 202, y + 6), fill=WT_COLORS[st])
                d.text((212, y), f"{st} {counts[st]}", font=_kr(24, 4), fill="#c0caf5", anchor="lm")
                y += 34
    d.text((24, 172), hint, font=_kr(19, 2), fill="#565f89", anchor="lm")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_message(title: str, lines: list[str], color: str = "#bb9af7") -> bytes:
    """워크트리 페이지의 넓은 칸: 안내/결과 메시지."""
    img = Image.new("RGB", (W, H), "#0d0e14")
    d = _Draw(img)
    d.text((24, 34), title, font=_kr(28, 6), fill=color, anchor="lm")
    for i, line in enumerate(lines[:4]):
        d.text((24, 78 + i * 30), line, font=_kr(21, 2), fill="#c0caf5", anchor="lm")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_market(indices, breadth: tuple[int, int], view_label: str) -> bytes:
    """히트맵 페이지의 넓은 칸: KOSPI·KOSDAQ + 상승/하락 종목 수 + 지금 보기."""
    img = Image.new("RGB", (W, H), "#0d0e14")
    d = _Draw(img)
    for i, ix in enumerate(indices[:2]):
        x = 24 + i * 220
        up = (ix.change or 0) >= 0
        col = "#e5484d" if up else "#3b6ff5"
        d.text((x, 30), ix.name, font=_kr(22, 6), fill="#a9b1d6", anchor="lm")
        d.text((x, 74), ix.price, font=_sf(40, b"Semibold"), fill="#e6e9f5", anchor="lm")
        d.text((x, 114), "-" if ix.change is None else f"{ix.change:+.2f}%", font=_sf(28, b"Semibold"), fill=col,
               anchor="lm")
    rise, fall = breadth
    d.text((24, 160), f"▲ {rise}", font=_kr(22, 4), fill="#e5484d", anchor="lm")
    d.text((120, 160), f"▼ {fall}", font=_kr(22, 4), fill="#3b6ff5", anchor="lm")
    status = "장중" if any(ix.status == "OPEN" for ix in indices) else "장 마감"
    d.text((W - 22, 160), f"{view_label} · {status}", font=_kr(20, 2), fill="#565f89", anchor="rm")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

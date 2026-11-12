"""시작 인트로와 홈(바로가기) 화면.

인트로(약 3초): 15칸이 물결처럼 켜진 뒤 한 칸에 한 글자씩 AGENT / DECK 로고 → 홈.
홈: 10칸 = 페이지 바로가기, 넓은 칸 = 업데이트 내용(지난번 이후 바뀐 것) · 받을 수 있는 새 버전.
"""

from __future__ import annotations

import io
import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from clock import EMOJI_FONT, _Draw, _kr, _sf

ROOT = Path(__file__).parent
SEEN = Path.home() / ".cache" / "d200" / "seen_version.json"
SIZE, GAP = 196, 40
PITCH = SIZE + GAP
WIDE = (458, 196)
WIDE_X = 3 * PITCH
FW, FH = WIDE_X + WIDE[0], 3 * SIZE + 2 * GAP
INTRO_SEC = 3.4
FPS = 6
PALETTE = ["#7aa2f7", "#bb9af7", "#f7768e", "#ff9e64", "#e0af68", "#9ece6a", "#73daca", "#7dcfff", "#2ac3de", "#c0caf5"]
LETTERS = "AGENTDECK"


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


def _rgb(h: str, k: float = 1.0) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(max(0, min(255, int(int(h[i:i + 2], 16) * k))) for i in (0, 2, 4))  # type: ignore[return-value]


def _key_box(k: int) -> tuple[int, int, int, int]:
    """칸 번호 → 화면 전체 좌표 (13 이상 = 넓은 칸)."""
    if k >= 13:
        return WIDE_X, 2 * PITCH, WIDE_X + WIDE[0], 2 * PITCH + WIDE[1]
    c, r = k % 5, k // 5
    return c * PITCH, r * PITCH, c * PITCH + SIZE, r * PITCH + SIZE


def _split(img: Image.Image) -> tuple[dict[int, bytes], bytes]:
    tiles = {k: _png(img.crop(_key_box(k))) for k in range(13)}
    return tiles, _png(img.crop(_key_box(13)))


# ---------- 인트로 ----------
def intro_frame(t: float, subtitle: str = "") -> tuple[dict[int, bytes], bytes]:
    """t 초 시점의 인트로 장면 → (칸 0~12, 넓은 칸)."""
    img = Image.new("RGB", (FW, FH), (8, 9, 14))
    d = ImageDraw.Draw(img)
    cx, cy = FW / 2, FH / 2
    keys = list(range(13)) + [13]
    for k in keys:  # 1) 가운데에서 바깥으로 물결처럼 켜졌다가 어두워짐
        x0, y0, x1, y1 = _key_box(k)
        dist = math.hypot((x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy) / 700
        a = max(0.0, 1 - abs(t - 0.25 - dist * 0.9) * 2.4)
        base = 0.16 if t > 1.3 else 0.0
        if a + base > 0:
            col = _rgb(PALETTE[k % len(PALETTE)], 0.25 + 0.75 * a)
            d.rounded_rectangle((x0 + 4, y0 + 4, x1 - 4, y1 - 4), 26, fill=col if a > base else _rgb(PALETTE[k % 10], base))
    if t > 1.2:  # 2) 한 칸에 한 글자씩 로고가 튀어나옴
        dd = _Draw(img)
        for i, ch in enumerate(LETTERS):
            k = i if i < 5 else i
            lt = t - 1.2 - i * 0.09
            if lt <= 0:
                continue
            pop = min(1.0, lt / 0.25)
            scale = 1.25 - 0.25 * pop if pop < 1 else 1.0
            x0, y0, x1, y1 = _key_box(k)
            col = PALETTE[i % len(PALETTE)]
            dd.rounded_rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 6), 28, fill=_rgb(col, 0.32 + 0.1 * pop),
                                 outline=_rgb(col), width=5)
            dd.text(((x0 + x1) / 2, (y0 + y1) / 2 + 4), ch, font=_sf(int(120 * scale), b"Bold"), fill=(245, 247, 255),
                    anchor="mm")
        # 마지막 칸: 덱 모양 아이콘
        x0, y0, x1, y1 = _key_box(9)
        if t > 2.1:
            for r in range(3):
                for c in range(5):
                    px, py = x0 + 38 + c * 25, y0 + 58 + r * 27
                    on = (r * 5 + c + int(t * FPS)) % 4 == 0
                    dd.rounded_rectangle((px, py, px + 19, py + 21), 5, fill=_rgb(PALETTE[(r * 5 + c) % 10], 1 if on else 0.45))
    if t > 2.0:  # 3) 아래 줄: 소개 문구
        dd = _Draw(img)
        for k, text in ((10, "AI 에이전트"), (11, "작업 현황"), (12, "대시보드")):
            x0, y0, x1, y1 = _key_box(k)
            dd.text(((x0 + x1) / 2, (y0 + y1) / 2), text, font=_kr(30, 6), fill=(200, 205, 225), anchor="mm")
        x0, y0, x1, y1 = _key_box(13)
        dd.text((x0 + 24, y0 + 60), "agentdeck", font=_sf(52, b"Bold"), fill=(245, 247, 255), anchor="lm")
        dd.text((x0 + 26, y0 + 118), subtitle, font=_kr(20, 4), fill=(150, 156, 190), anchor="lm")
        dd.text((x0 + 26, y0 + 160), "아무 칸: 건너뛰기", font=_kr(16, 2), fill=(110, 116, 150), anchor="lm")
    return _split(img)


# ---------- 업데이트 내용 ----------
def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def _clean(subject: str) -> str:
    """'feat(race): 경주 중 …' → '경주 중 …'"""
    return re.sub(r"^\w+(\([^)]*\))?!?:\s*", "", subject).strip()


def whats_new(limit: int = 6) -> list[str]:
    """지난번에 본 버전 이후 들어온 변경 (처음이면 최근 3개)."""
    head = _git("rev-parse", "HEAD").strip()
    try:
        seen = json.loads(SEEN.read_text()).get("sha", "")
    except Exception:
        seen = ""
    if seen and seen != head:
        out = _git("log", "--format=%s", f"{seen}..HEAD", f"-{limit}")
    else:
        out = _git("log", "--format=%s", "-3")
    return [_clean(s) for s in out.splitlines() if s.strip()]


def is_new() -> bool:
    try:
        return json.loads(SEEN.read_text()).get("sha", "") != _git("rev-parse", "HEAD").strip()
    except Exception:
        return True


def mark_seen() -> None:
    try:
        SEEN.parent.mkdir(parents=True, exist_ok=True)
        SEEN.write_text(json.dumps({"sha": _git("rev-parse", "HEAD").strip()}))
    except Exception:
        pass


def incoming(limit: int = 4) -> list[str]:
    """아직 받지 않은 새 버전의 변경 (업데이트 확인을 한 뒤에만 있음)."""
    out = _git("log", "--format=%s", "HEAD..@{u}", f"-{limit}")
    return [_clean(s) for s in out.splitlines() if s.strip()]


def version_text() -> str:
    out = _git("log", "-1", "--format=%cd", "--date=format:%Y.%m.%d").strip()
    return f"버전 {out}" if out else ""


# ---------- 홈 (바로가기) ----------


@lru_cache(maxsize=32)
def _emoji(ch: str, size: int) -> Image.Image | None:
    try:
        img = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((110, 110), ch, font=ImageFont.truetype(EMOJI_FONT, 160), embedded_color=True,
                                 anchor="mm")
        img = img.crop(img.getbbox())
        img.thumbnail((size, size), Image.LANCZOS)
        return img
    except Exception:
        return None


ICONS = ROOT / "assets" / "icons"


@lru_cache(maxsize=32)
def _icon(name: str, size: int) -> Image.Image | None:
    p = ICONS / f"{name}.png"
    if p.exists():
        im = Image.open(p).convert("RGBA")
        im.thumbnail((size, size), Image.LANCZOS)
        return im
    return _emoji(name, size) if not name.isascii() else None


@lru_cache(maxsize=32)
def shortcut_tile(title: str, sub: str, icon: str, color: str) -> bytes:
    """바로가기 칸: 색 그라데이션 카드 + 앱 아이콘 + 이름."""
    col = _rgb(color)
    img = Image.new("RGB", (SIZE, SIZE), (12, 13, 20))
    card = Image.new("RGB", (SIZE, SIZE))
    cd = ImageDraw.Draw(card)
    for y in range(SIZE):  # 위는 은은한 색, 아래로 갈수록 어둡게
        k = 1 - y / SIZE
        cd.line((0, y, SIZE, y), fill=tuple(int(18 + (c * 0.42 - 18) * k * k) for c in col))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((6, 6, 189, 189), 30, fill=255)
    img.paste(card, (0, 0), mask)
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))  # 아이콘 뒤 둥근 빛
    ImageDraw.Draw(glow).ellipse((48, 18, 148, 118), fill=(*col, 70))
    img.paste(glow, (0, 0), glow)
    d = _Draw(img)
    d.rounded_rectangle((6, 6, 189, 189), 30, outline=tuple(min(255, int(c * 0.9)) for c in col), width=2)
    ic = _icon(icon, 98)
    if ic:
        img.paste(ic, (98 - ic.width // 2, 70 - ic.height // 2), ic)
    d.text((98, 146), title, font=_kr(26 if len(title) <= 4 else 22, 6), fill=(244, 246, 252), anchor="mm")
    if sub:
        d.text((98, 174), sub, font=_kr(15, 4), fill=(176, 182, 210), anchor="mm")
    return _png(img)


def home_wide(notes: list[str], fresh: bool, pending: list[str], behind: int, page: int = 0) -> bytes:
    """넓은 칸: 업데이트 내용. 새 버전이 있으면 그 내용과 '2초 누르기' 안내를 먼저."""
    img = Image.new("RGB", WIDE, (13, 14, 20))
    d = _Draw(img)
    if behind:
        d.text((20, 26), f"새 버전 {behind}개 · 여기 2초 누르면 업데이트", font=_kr(20, 6), fill=(158, 206, 106), anchor="lm")
        items = pending
    else:
        d.text((20, 26), "새로 바뀐 것" if fresh else "최근 업데이트", font=_kr(22, 6),
               fill=(255, 158, 100) if fresh else (122, 162, 247), anchor="lm")
        d.text((438, 26), version_text(), font=_kr(15, 2), fill=(110, 116, 150), anchor="rm")
        items = notes
    per = 4
    pages = max(1, math.ceil(len(items) / per))
    shown = items[(page % pages) * per:(page % pages) * per + per] or ["변경 내용을 읽지 못했어요"]
    for i, text in enumerate(shown):
        y = 64 + i * 32
        d.ellipse((22, y - 4, 30, y + 4), fill=(255, 158, 100) if (fresh or behind) else (122, 162, 247))
        size = 18
        while size > 13 and d.textlength(text, font=_kr(size, 4)) > 400:
            size -= 1
        if d.textlength(text, font=_kr(size, 4)) > 400:
            while text and d.textlength(text + "…", font=_kr(size, 4)) > 400:
                text = text[:-1]
            text += "…"
        d.text((40, y), text, font=_kr(size, 4), fill=(222, 226, 240), anchor="lm")
    if pages > 1:
        d.text((438, 186), f"{page % pages + 1}/{pages} · 누르면 다음", font=_kr(13, 2), fill=(110, 116, 150), anchor="rm")
    return _png(img)

"""게임 페이지: 두더지 잡기 · 순서 기억 · 짝 맞추기 · 슬롯머신 · 블랙잭 · 포커 대결 · 경마.

판은 위 두 줄 10칸(0~9). 아래 줄은 페이지 넘김 버튼 그대로, 넓은 칸은 점수판.
입력은 누르는 순간(press)에 처리해 반응을 빠르게 한다. 화면은 상태가 바뀔 때만 다시 보낸다.
"""

from __future__ import annotations

import io
import itertools
import json
import math
import random
import threading
import time
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from clock import EMOJI_FONT, _Draw, _kr
from sfx import play

BOARD = 10
SIZE = 196
WIDE = (458, 196)
SAVE = Path.home() / ".cache" / "d200" / "games.json"

GAMES = ["mole", "simon", "pairs", "slot", "bj", "poker", "race"]  # 메뉴 칸 순서 (0번 칸부터)
try:  # AI 스타트업 타이쿤 (보드게임, tycoon.py). 고장 나도 나머지 게임은 그대로
    from tycoon import Tycoon
    GAMES.append("tycoon")
except Exception as _te:
    print(f"tycoon load error: {_te}", flush=True)
    Tycoon = None
LOWER_IS_BETTER = {"pairs"}  # 짝 맞추기는 시도 횟수가 적을수록 좋은 기록
PAIR_CARDS = ["🐟", "🐙", "🦀", "🐢", "🦈"]  # 어항 친구들 5쌍
SLOT_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "💎", "7"]
SLOT_PAY = {"7": 50, "💎": 30, "⭐": 15, "🔔": 10, "🍋": 6, "🍒": 5}  # 세 개가 같을 때
SLOT_REELS = (1, 2, 3)  # 릴이 보이는 칸 (윗줄 가운데)
SLOT_STOPS = (6, 7, 8)  # 각 릴을 멈추는 버튼 (바로 아래 칸)
SLOT_LEVERS = (0, 4, 5, 9)  # 돌리기 (양쪽 끝 칸)
SLOT_START = 20  # 슬롯·블랙잭이 같이 쓰는 코인
BJ_HIT, BJ_STAND = 4, 9  # 블랙잭: 윗줄 끝 = 한 장 더, 아랫줄 끝 = 그만 (베팅 중엔 딜 / 베팅액)
BJ_BETS = [1, 2, 5, 10]
SUITS = "♠♥♦♣"
POKER_NAMES = ["하이카드", "원페어", "투페어", "트리플", "스트레이트", "플러시", "풀하우스", "포카드",
               "스트레이트 플러시", "로열 플러시"]
POKER_BONUS = {4: 4, 5: 6, 6: 9, 7: 25, 8: 50, 9: 250}  # 이겼을 때 스트레이트 이상이면 배당이 커진다 (그 밖엔 1배)
POKER_OPEN = (0, 1)  # 상대 카드 중 처음부터 보이는 칸
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
MOLE_SEC = 30  # 두더지 한 판 길이
SIMON_COLORS = ["#f7768e", "#ff9e64", "#e0af68", "#9ece6a", "#73daca",
                "#7dcfff", "#7aa2f7", "#bb9af7", "#c0caf5", "#f4b8e4"]


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


def _rgb(hex_: str, k: float = 1.0) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return tuple(min(255, int(int(h[i:i + 2], 16) * k)) for i in (0, 2, 4))  # type: ignore[return-value]


# ---------- 칸 그림 (상태별로 캐시) ----------
@lru_cache(maxsize=64)
def mole_tile(state: str) -> bytes:
    """state: empty | mole | gold | bomb | hit | boom | miss"""
    img = Image.new("RGB", (SIZE, SIZE), (58, 92, 52))
    d = _Draw(img)
    for i in range(14):  # 잔디 점
        x, y = (i * 53) % SIZE, (i * 97) % 70 + 6
        d.line((x, y, x + 3, y - 7), fill=(84, 130, 70), width=3)
    d.ellipse((30, 128, 166, 176), fill=(70, 46, 30))  # 구멍
    if state in ("mole", "gold", "hit"):
        body = (232, 190, 70) if state == "gold" else (140, 98, 66)
        d.rounded_rectangle((52, 58, 144, 160), 40, fill=body)
        d.ellipse((30, 140, 166, 182), fill=(58, 92, 52))  # 구멍 앞 흙 둔덕
        d.ellipse((30, 146, 166, 188), fill=(96, 66, 42))
        if state == "hit":  # X 눈 + 별
            for cx in (80, 116):
                d.line((cx - 8, 86, cx + 8, 102), fill=(30, 20, 20), width=5)
                d.line((cx - 8, 102, cx + 8, 86), fill=(30, 20, 20), width=5)
            for sx, sy in ((40, 40), (150, 34), (98, 22)):
                d.regular_polygon((sx, sy, 13), 5, fill=(255, 225, 90))
        else:
            for cx in (80, 116):
                d.ellipse((cx - 8, 84, cx + 8, 100), fill=(20, 16, 16))
                d.ellipse((cx - 3, 87, cx + 2, 92), fill=(255, 255, 255))
        d.ellipse((88, 104, 108, 120), fill=(240, 130, 150))  # 코
        d.ellipse((60, 124, 84, 140), fill=(236, 226, 210))  # 앞발
        d.ellipse((112, 124, 136, 140), fill=(236, 226, 210))
        if state == "gold":
            d.text((98, 40), "+3", font=_kr(26, 6), fill=(255, 245, 190), anchor="mm")
    elif state in ("bomb", "boom"):
        if state == "boom":
            d.regular_polygon((98, 110, 78), 12, fill=(255, 150, 60))
            d.regular_polygon((98, 110, 50), 12, fill=(255, 230, 120))
            d.text((98, 110), "-3", font=_kr(40, 6), fill=(120, 30, 20), anchor="mm")
        else:
            d.ellipse((56, 70, 140, 154), fill=(30, 30, 38))
            d.ellipse((72, 84, 90, 102), fill=(90, 90, 110))
            d.line((118, 76, 134, 50), fill=(200, 170, 120), width=5)
            d.regular_polygon((136, 46, 12), 6, fill=(255, 190, 70))
    elif state == "miss":
        d.text((98, 80), "헛방", font=_kr(30, 6), fill=(220, 235, 210), anchor="mm")
    return _png(img)


@lru_cache(maxsize=64)
def simon_tile(idx: int, lit: bool, mark: str = "") -> bytes:
    color = SIMON_COLORS[idx]
    img = Image.new("RGB", (SIZE, SIZE), (13, 14, 20))
    d = _Draw(img)
    fill = _rgb(color) if lit else _rgb(color, 0.22)
    d.rounded_rectangle((14, 14, 182, 182), 30, fill=fill)
    if lit:
        d.rounded_rectangle((14, 14, 182, 182), 30, outline=(255, 255, 255), width=6)
    if mark == "✕":  # 틀린 칸: 굵은 X (글꼴에 ✕ 가 없어 직접 그림)
        d.line((60, 60, 136, 136), fill=(255, 90, 100), width=14)
        d.line((60, 136, 136, 60), fill=(255, 90, 100), width=14)
    elif mark:
        d.text((98, 98), mark, font=_kr(64, 6), fill=(255, 255, 255), anchor="mm")
    return _png(img)


@lru_cache(maxsize=32)
def menu_tile(kind: str, best: str) -> bytes:
    img = Image.new("RGB", (SIZE, SIZE), (24, 26, 38))
    d = _Draw(img)
    title = {"mole": "두더지 잡기", "simon": "순서 기억", "pairs": "짝 맞추기", "slot": "슬롯머신", "bj": "블랙잭",
             "poker": "포커 대결", "race": "경마"}[kind]
    if kind == "mole":
        d.ellipse((48, 120, 148, 150), fill=(70, 46, 30))
        d.rounded_rectangle((66, 48, 130, 136), 30, fill=(140, 98, 66))
        for cx in (86, 110):
            d.ellipse((cx - 6, 70, cx + 6, 82), fill=(20, 16, 16))
        d.ellipse((90, 88, 106, 100), fill=(240, 130, 150))
    elif kind == "simon":
        for i, c in enumerate(SIMON_COLORS[:4]):
            x, y = 54 + (i % 2) * 46, 52 + (i // 2) * 46
            d.rounded_rectangle((x, y, x + 40, y + 40), 10, fill=_rgb(c))
    elif kind == "pairs":
        for k, (x, face) in enumerate(((44, "🐙"), (102, "🐙"))):
            d.rounded_rectangle((x, 50, x + 50, 140), 10, fill=(236, 238, 248) if k else (60, 72, 130))
            if k:
                _paste_center(img, _emoji(face, 40), x + 25, 95)
            else:
                d.text((x + 25, 95), "?", font=_kr(34, 6), fill=(170, 182, 235), anchor="mm")
    elif kind == "poker":
        for k, c in enumerate((("10", "♠"), ("J", "♠"), ("Q", "♠"))):
            img.paste(Image.open(io.BytesIO(play_card(c, "", 0.46))), (34 + k * 44, 50))
    elif kind == "race":
        d.rectangle((24, 118, 172, 140), fill=(176, 128, 82))
        for y in range(46, 140, 12):  # 결승선
            for c in range(2):
                d.rectangle((150 + c * 8, y, 157 + c * 8, y + 11), fill=(20, 20, 24) if (y // 12 + c) % 2 else (245, 245, 245))
        _paste_center(img, _emoji("🏇", 84).transpose(Image.FLIP_LEFT_RIGHT), 92, 94)
    elif kind == "bj":
        img.paste(Image.open(io.BytesIO(play_card(("A", "♠"), "", 0.55))), (36, 46))
        img.paste(Image.open(io.BytesIO(play_card(("K", "♥"), "", 0.55))), (64, 54))
    else:
        for k in range(3):
            x = 40 + k * 40
            d.rounded_rectangle((x, 60, x + 36, 130), 8, fill=(250, 246, 236))
            _seven(d, x + 18, 95, 44)
    d.text((98, 22), title, font=_kr(24, 6), fill=(230, 233, 245), anchor="mm")
    d.text((98, 172), best, font=_kr(20, 4), fill=(169, 177, 214), anchor="mm")
    return _png(img)


@lru_cache(maxsize=32)
def _emoji(ch: str, size: int) -> Image.Image:
    """애플 컬러 이모지를 160px 로 그린 뒤 size 로 줄인다 (글꼴이 160 크기만 지원)."""
    img = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
    try:
        ImageDraw.Draw(img).text((110, 110), ch, font=ImageFont.truetype(EMOJI_FONT, 160), embedded_color=True,
                                 anchor="mm")
        img = img.crop(img.getbbox())
    except Exception:  # 이모지 글꼴이 없으면 글자로
        img = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((80, 80), ch, font=_kr(110, 6), fill=(240, 240, 240), anchor="mm")
    img.thumbnail((size, size), Image.LANCZOS)
    return img


def _paste_center(base: Image.Image, icon: Image.Image, cx: int, cy: int) -> None:
    base.paste(icon, (cx - icon.width // 2, cy - icon.height // 2), icon)


def _seven(d, cx: int, cy: int, size: int) -> None:
    d.text((cx, cy), "7", font=_kr(size, 6), fill=(235, 60, 70), anchor="mm", stroke_width=max(2, size // 16),
           stroke_fill=(255, 220, 120))


@lru_cache(maxsize=64)
def card_tile(face: str | None, state: str = "down") -> bytes:
    """짝 맞추기 카드. state: down(뒷면) | up(뒤집음) | done(맞춤) | wrong(틀린 한 쌍)"""
    img = Image.new("RGB", (SIZE, SIZE), (13, 14, 20))
    d = _Draw(img)
    if state == "down":
        d.rounded_rectangle((16, 10, 180, 186), 22, fill=(60, 72, 130))
        d.rounded_rectangle((28, 22, 168, 174), 16, outline=(120, 135, 200), width=4)
        d.text((98, 98), "?", font=_kr(70, 6), fill=(170, 182, 235), anchor="mm")
        return _png(img)
    bg = {"up": (236, 238, 248), "done": (205, 240, 210), "wrong": (250, 210, 215)}[state]
    d.rounded_rectangle((16, 10, 180, 186), 22, fill=bg)
    if state == "done":
        d.rounded_rectangle((16, 10, 180, 186), 22, outline=(90, 190, 110), width=6)
    _paste_center(img, _emoji(face or "?", 110), 98, 98)
    return _png(img)


@lru_cache(maxsize=96)
def reel_tile(sym: str, glow: bool = False, spinning: bool = False) -> bytes:
    img = Image.new("RGB", (SIZE, SIZE), (40, 18, 30) if not glow else (120, 70, 20))
    d = _Draw(img)
    d.rounded_rectangle((12, 12, 184, 184), 20, fill=(250, 246, 236), outline=(255, 205, 90) if glow else (150, 110, 70),
                        width=8 if glow else 5)
    if spinning:  # 돌아가는 느낌: 위아래 잔상 줄
        for y in (34, 162):
            d.line((40, y, 156, y), fill=(210, 200, 185), width=6)
    if sym == "7":
        _seven(d, 98, 98, 120)
    else:
        _paste_center(img, _emoji(sym, 112), 98, 98)
    return _png(img)


@lru_cache(maxsize=16)
def slot_button(kind: str, active: bool = True) -> bytes:
    """kind: stop | stopped | lever | wait"""
    img = Image.new("RGB", (SIZE, SIZE), (13, 14, 20))
    d = _Draw(img)
    if kind in ("stop", "stopped"):
        col = (230, 70, 80) if kind == "stop" else (70, 60, 70)
        d.ellipse((38, 38, 158, 158), fill=col, outline=(255, 255, 255) if kind == "stop" else (100, 90, 100), width=6)
        d.text((98, 98), "STOP", font=_kr(30, 6), fill=(255, 255, 255) if kind == "stop" else (150, 140, 150),
               anchor="mm")
    else:
        on = kind == "lever"
        d.rounded_rectangle((86, 50, 110, 160), 10, fill=(170, 170, 185) if on else (70, 70, 80))
        d.ellipse((66, 18, 130, 82), fill=(235, 60, 70) if on else (90, 60, 65))
        d.text((98, 178), "돌리기", font=_kr(22, 6), fill=(230, 233, 245) if on else (100, 100, 115), anchor="mm")
    return _png(img)


@lru_cache(maxsize=256)
def play_card(card: tuple[str, str] | None, glow: str = "", scale: float = 1.0) -> bytes:
    """트럼프 한 장. card=None 이면 뒷면. glow: win | lose | ''"""
    w, h = int(118 * scale), int(166 * scale)
    img = Image.new("RGB", (w, h), (13, 14, 20)) if scale != 1.0 else Image.new("RGB", (SIZE, SIZE), (22, 70, 48))
    d = _Draw(img)
    x0, y0 = (0, 0) if scale != 1.0 else ((SIZE - w) // 2, (SIZE - h) // 2)
    box = (x0, y0, x0 + w - 1, y0 + h - 1)
    if card is None:  # 뒷면: 사선 무늬를 카드 모양 안에만
        back = Image.new("RGB", (w, h), (50, 70, 150))
        bd = ImageDraw.Draw(back)
        for k in range(-h, w, max(4, int(16 * scale))):
            bd.line((k, 0, k + h, h), fill=(75, 95, 175), width=max(1, int(3 * scale)))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), int(14 * scale), fill=255)
        img.paste(back, (x0, y0), mask)
        d.rounded_rectangle(box, int(14 * scale), outline=(235, 235, 245), width=max(2, int(5 * scale)))
        return _png(img)
    rank, suit = card
    red = suit in "♥♦"
    col = (210, 40, 50) if red else (25, 25, 35)
    edge = {"win": (90, 200, 110), "lose": (230, 80, 90), "hold": (250, 200, 60)}.get(glow, (200, 200, 210))
    d.rounded_rectangle(box, int(14 * scale), fill=(252, 252, 248), outline=edge, width=max(2, int((7 if glow else 3) * scale)))
    d.text((x0 + int(12 * scale), y0 + int(8 * scale)), rank, font=_kr(int(40 * scale), 6), fill=col, anchor="lt")
    d.text((x0 + w // 2, y0 + int(h * 0.62)), suit, font=_kr(int(78 * scale), 6), fill=col, anchor="mm")
    return _png(img)


@lru_cache(maxsize=128)
def hand_tile(cards: tuple, glow: str = "") -> bytes:
    """카드 0~2장을 한 칸에. 두 장이면 겹쳐서 작게."""
    if len(cards) <= 1:
        if not cards:
            return _png(Image.new("RGB", (SIZE, SIZE), (22, 70, 48)))
        return play_card(cards[0], glow)
    img = Image.new("RGB", (SIZE, SIZE), (22, 70, 48))
    for k, c in enumerate(cards[:2]):
        im = Image.open(io.BytesIO(play_card(c, glow, 0.78)))
        img.paste(im, (14 + k * 72, 22 + k * 16))
    return _png(img)


@lru_cache(maxsize=32)
def bj_button(label: str, sub: str, color: str, enabled: bool = True) -> bytes:
    img = Image.new("RGB", (SIZE, SIZE), (13, 14, 20))
    d = _Draw(img)
    fill = _rgb(color) if enabled else (55, 58, 70)
    d.rounded_rectangle((14, 14, 182, 182), 26, fill=fill)
    tc = (20, 20, 28) if enabled else (120, 122, 135)
    d.text((98, 88), label, font=_kr(40 if len(label) <= 3 else 32, 6), fill=tc, anchor="mm")
    if sub:
        d.text((98, 140), sub, font=_kr(22, 4), fill=tc, anchor="mm")
    return _png(img)


def _layout(cards: list, slots: int = 4) -> list[tuple]:
    """카드 목록을 칸 slots 개에 나눈다. 넘치면 뒤쪽 칸부터 두 장씩."""
    sizes = [1] * min(len(cards), slots) + [0] * max(0, slots - len(cards))
    extra = len(cards) - slots
    k = slots - 1
    while extra > 0 and k >= 0:
        sizes[k] += 1
        extra -= 1
        k -= 1
    out, i = [], 0
    for n in sizes:
        out.append(tuple(cards[i:i + n]))
        i += n
    return out


def poker_rank(cards: list) -> tuple[int, tuple]:
    """5장 족보 → (족보 번호 0~9, 같은 족보끼리 비교할 숫자들). 번호는 POKER_NAMES 순서."""
    order = {r: i + 2 for i, r in enumerate(["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"])}
    vals = [order[r] for r, _ in cards]
    groups = sorted(((vals.count(v), v) for v in set(vals)), reverse=True)  # (장수, 숫자) 많은 순
    tie = tuple(v for _, v in groups)
    flush = len({s for _, s in cards}) == 1
    uniq = sorted(set(vals))
    straight = len(uniq) == 5 and uniq[-1] - uniq[0] == 4
    if uniq == [2, 3, 4, 5, 14]:  # A-2-3-4-5
        straight, tie = True, (5,)
    elif straight:
        tie = (uniq[-1],)
    if straight and flush:
        return (9 if tie == (14,) else 8), tie
    if groups[0][0] == 4:
        return 7, tie
    if groups[0][0] == 3 and groups[1][0] == 2:
        return 6, tie
    if flush:
        return 5, tuple(sorted(vals, reverse=True))
    if straight:
        return 4, tie
    if groups[0][0] == 3:
        return 3, tie
    if groups[0][0] == 2 and groups[1][0] == 2:
        return 2, tie
    if groups[0][0] == 2:
        return 1, tie
    return 0, tuple(sorted(vals, reverse=True))


def poker_ai_holds(cards: list) -> list[bool]:
    """상대(컴퓨터)가 남길 카드: 족보가 있으면 그대로, 같은 무늬 4장이면 그 4장, 아니면 Q 이상 한 장."""
    cat, _ = poker_rank(cards)
    if cat >= 4:
        return [True] * 5
    ranks = [r for r, _ in cards]
    if cat >= 1:
        return [ranks.count(r) >= 2 for r in ranks]
    suits = [s for _, s in cards]
    for s in set(suits):
        if suits.count(s) == 4:
            return [x == s for x in suits]
    best = max(range(5), key=lambda i: RANKS.index(ranks[i]) if ranks[i] != "A" else 99)
    return [i == best and ranks[i] in ("Q", "K", "A") for i in range(5)]


@lru_cache(maxsize=128)
def held_card(card: tuple[str, str]) -> bytes:
    """킵한 카드: 노란 테두리 + 아래 띠."""
    img = Image.open(io.BytesIO(play_card(card, "hold")))
    d = _Draw(img)
    d.rounded_rectangle((52, 160, 144, 190), 10, fill=(250, 200, 60))
    d.text((98, 175), "킵", font=_kr(22, 6), fill=(30, 25, 10), anchor="mm")
    return _png(img)


def hand_value(cards: list) -> tuple[int, bool]:
    """(합계, 소프트 여부). A 는 1 또는 11."""
    total = sum(10 if r in "JQK" or r == "10" else (1 if r == "A" else int(r)) for r, _ in cards)
    soft = any(r == "A" for r, _ in cards) and total + 10 <= 21
    return (total + 10 if soft else total), soft


@lru_cache(maxsize=4)
def blank_tile() -> bytes:
    return _png(Image.new("RGB", (SIZE, SIZE), (13, 14, 20)))


def wide_panel(title: str, big: str, lines: list[str], color: str, bar: float | None = None) -> bytes:
    img = Image.new("RGB", WIDE, "#0d0e14")
    d = _Draw(img)
    d.text((24, 34), title, font=_kr(26, 6), fill=color, anchor="lm")
    d.text((434, 96), big, font=_kr(64, 6), fill="#e6e9f5", anchor="rm")
    from i18n import tr

    room = 434 - 24 - 16 - (d.textlength(tr(big) or "", font=_kr(64, 6)) if big else 0)  # 큰 숫자와 겹치지 않게
    for i, line in enumerate(lines[:3]):
        size = 21
        while size > 14 and d.textlength(tr(line) or "", font=_kr(size, 2)) > (room if 66 <= 82 + i * 30 <= 126 else 410):
            size -= 1
        d.text((24, 82 + i * 30), line, font=_kr(size, 2), fill="#c0caf5", anchor="lm")
    if bar is not None:  # 남은 시간 막대
        d.rounded_rectangle((24, 170, 434, 180), 5, fill="#1f2335")
        w = int(410 * max(0.0, min(1.0, bar)))
        if w > 6:
            d.rounded_rectangle((24, 170, 24 + w, 180), 5, fill=color)
    return _png(img)


# ---------- 경마 ----------
RACE_FPS = 5  # 경주 화면 초당 장면 수 (어항과 같은 속도)
RACE_W = SIZE * 5  # 윗줄 다섯 칸을 이어 붙인 경주로
RACE_X0, RACE_X1 = 78, RACE_W - 50  # 출발선 · 결승선 (말 코끝 기준)
RACE_LANE_Y = [62 + k * 28 for k in range(5)]  # 레인별 말 발 위치
HORSE_NAMES = ["번개", "질풍", "천둥", "바람", "별빛", "흑진주", "은하", "태풍", "불꽃", "청룡", "백설", "먹구름"]
HORSE_COLORS = ["#f7768e", "#7aa2f7", "#e0af68", "#9ece6a", "#bb9af7"]  # 1~5번 등번호 색


def race_sim(power: list[float], rnd: random.Random) -> tuple[list[list[float]], list[int]]:
    """한 경주를 장면 단위로 미리 계산. 반환: (장면마다 말 5마리의 위치 0=출발·1=결승, 착순).
    말마다 힘(power)·기복(속도가 천천히 오르내림)·막판 스퍼트가 달라 역전이 자주 난다."""
    pace = [0.0] * 5
    kick = [rnd.uniform(0.9, 1.16) for _ in range(5)]  # 마지막 직선에서의 뒷심
    kick_at = [rnd.uniform(0.62, 0.8) for _ in range(5)]
    pos = [0.0] * 5
    cross = [1e9] * 5  # 결승선을 넘은 시점 (장면 단위, 소수점까지)
    frames = [pos[:]]
    base = 1 / 42  # 평균 42장면(약 8초)에 결승
    while min(pos) < 1.0 and len(frames) < 120:
        for i in range(5):
            if pos[i] >= 1.0:  # 결승선을 지난 말은 속도를 줄이며 조금 더 달린다 (착순이 눈에 보이게)
                pos[i] = min(1.05, pos[i] + base * 0.5)
                continue
            pace[i] = max(-0.16, min(0.16, pace[i] * 0.85 + rnd.gauss(0, 0.06)))
            v = base * power[i] * (1 + pace[i])
            if pos[i] > kick_at[i]:
                v *= kick[i]
            if len(frames) < 4:  # 출발 직후엔 천천히 속도를 올린다
                v *= 0.45 + 0.18 * len(frames)
            if pos[i] + v >= 1.0:  # 결승선을 넘은 장면
                cross[i] = len(frames) - 1 + (1.0 - pos[i]) / v
                pos[i] = 1.0 + base * 0.3
            else:
                pos[i] += v
        frames.append(pos[:])
    for _ in range(3):  # 마지막 말이 들어온 뒤 잠깐 더
        frames.append([min(1.05, p + base * 0.5) for p in frames[-1]])
    return frames, sorted(range(5), key=lambda i: cross[i])


BET_TYPES = {1: "단승", 2: "복승", 3: "삼복승"}  # 고른 말 수 → 승식 (한국 경마 이름). 두 마리는 쌍승으로 바꿀 수 있다
BET_RULES = {1: "1착을 맞히면", 2: "두 마리가 1·2착 (순서 상관없이)", 3: "세 마리가 1·2·3착 (순서 상관없이)",
             "exacta": "고른 순서대로 1착·2착"}
RACE_TOGGLE = 0  # 두 마리를 골랐을 때 0번 칸 = 복승 ⇄ 쌍승
RACE_CHIPS = (1, 2, 3, 4)  # 대기 중 윗줄에 베팅액 칩을 띄우는 칸 (0번 칸은 출발 게이트라 비워 둔다)


def race_book(power: list[float], rnd: random.Random, n: int = 1200) -> dict:
    """여러 번 미리 달려 보고 승식별 배당을 정한다 (돌려주는 돈 = 건 코인 × 배당, 약 3% 하우스 몫).
    키: 고른 말 묶음 — 한 마리(단승) · 두 마리(복승: 1·2착) · 세 마리(삼복승: 1·2·3착),
    순서가 있는 (1착, 2착) 튜플은 쌍승."""
    hits: dict = {}
    for _ in range(n):
        order = race_sim(power, rnd)[1]
        for key in (frozenset(order[:1]), frozenset(order[:2]), frozenset(order[:3]), tuple(order[:2])):
            hits[key] = hits.get(key, 0) + 1
    book: dict = {}
    for combo in itertools.permutations(range(5), 2):
        p = max(hits.get(combo, 0), 0.5) / n
        book[combo] = min(500.0, max(1.2, round(0.97 / p, 1)))
    for k in (1, 2, 3):
        for combo in itertools.combinations(range(5), k):
            p = max(hits.get(frozenset(combo), 0), 0.5) / n  # 한 번도 안 나온 조합도 배당은 있게
            book[frozenset(combo)] = min(300.0, max(1.2, round(0.97 / p, 1)))
    return book


@lru_cache(maxsize=4)
def _horse(size: int, frame: int) -> Image.Image:
    """오른쪽으로 달리는 말 (이모지를 뒤집고, 장면마다 살짝 기울여 뛰는 느낌)."""
    h = _emoji("🏇", size).transpose(Image.FLIP_LEFT_RIGHT)
    return h.rotate(4 if frame else -3, resample=Image.BICUBIC, expand=True)


@lru_cache(maxsize=2)
def _race_bg(gate: bool) -> Image.Image:
    img = Image.new("RGB", (RACE_W, SIZE), (46, 120, 66))
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    d.rectangle((0, 0, RACE_W, 22), fill=(30, 34, 52))  # 관중석
    for _ in range(260):
        x, y = rnd.randrange(RACE_W), rnd.randrange(3, 20)
        d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=rnd.choice([(247, 118, 142), (122, 162, 247), (224, 175, 104),
                                                                  (158, 206, 106), (235, 235, 245), (187, 154, 247)]))
    d.rectangle((0, 22, RACE_W, 27), fill=(235, 235, 240))  # 안쪽 난간
    d.rectangle((0, 28, RACE_W, SIZE - 14), fill=(176, 128, 82))  # 흙 주로
    for k in range(5):  # 레인 구분선
        y = RACE_LANE_Y[k] + 4
        d.line((0, y, RACE_W, y), fill=(160, 114, 72), width=2)
    for x in range(0, RACE_W, 24):  # 흙 질감
        for y in range(32, SIZE - 16, 9):
            if rnd.random() < 0.35:
                d.point((x + rnd.randrange(24), y + rnd.randrange(9)), fill=(150, 104, 64))
    d.rectangle((0, SIZE - 14, RACE_W, SIZE - 10), fill=(235, 235, 240))  # 바깥 난간
    for x in range(0, RACE_W, 40):
        d.rectangle((x, SIZE - 14, x + 3, SIZE), fill=(220, 220, 228))
    fx = RACE_X1 + 4  # 결승선 (체크무늬)
    for y in range(28, SIZE - 14, 8):
        for c in range(2):
            d.rectangle((fx + c * 6, y, fx + c * 6 + 5, y + 7), fill=(20, 20, 24) if (y // 8 + c) % 2 else (245, 245, 245))
    d.rectangle((fx + 2, 6, fx + 9, 28), fill=(230, 60, 70))  # 결승 기둥
    for k in range(10):  # 거리 표시 기둥
        x = RACE_X0 + (RACE_X1 - RACE_X0) * k // 10
        d.rectangle((x, 22, x + 2, 27), fill=(230, 60, 70))
    if gate:  # 출발 게이트
        d.rectangle((RACE_X0 + 4, 26, RACE_X0 + 12, SIZE - 12), fill=(90, 94, 110))
        for y in RACE_LANE_Y:
            d.rectangle((RACE_X0 + 4, y - 22, RACE_X0 + 12, y + 2), fill=(200, 204, 214))
    return img


def race_track(pos: list[float], frame: int, gate: bool = False, mine: tuple[int, ...] = (),
               winner: int | None = None) -> list[bytes]:
    """윗줄 다섯 칸에 이어지는 경주로. 반환: 칸 0~4 PNG."""
    img = _race_bg(gate).copy()
    d = ImageDraw.Draw(img)
    for i in range(5):
        x = RACE_X0 + (RACE_X1 - RACE_X0) * min(pos[i], 1.05)
        y = RACE_LANE_Y[i]
        run = 0.0 < pos[i] < 1.05
        if run:  # 뒤로 날리는 흙먼지
            for k in range(3):
                dx = 66 + k * 9 + ((frame + i + k) % 3) * 4
                r = 5 - k
                d.ellipse((x - dx - r, y - 4 - r - k * 2, x - dx + r, y - 4 + r - k * 2), fill=(214, 180, 140))
        hop = 0 if not run else (-3 if (frame + i) % 2 else 1)
        h = _horse(52, (frame + i) % 2 if run else 0)
        img.paste(h, (int(x - h.width), int(y - h.height + 6 + hop)), h)
        bx, by = int(x - h.width - 8), int(y - 14 + hop)  # 등번호: 꼬리 뒤
        if i in mine:
            d.ellipse((bx - 14, by - 14, bx + 14, by + 14), fill=(250, 210, 60))
        d.ellipse((bx - 11, by - 11, bx + 11, by + 11), fill=_rgb(HORSE_COLORS[i]), outline=(25, 25, 30))
        d.text((bx, by + 1), str(i + 1), font=_kr(16, 6), fill=(20, 20, 28), anchor="mm")
        if winner == i:  # 우승 말 머리 위 왕관
            _paste_center(img, _emoji("👑", 24), bx - 26, by)
    return [_png(img.crop((k * SIZE, 0, (k + 1) * SIZE, SIZE))) for k in range(5)]


# 경주 중 큰 화면: 위 10칸(두 줄) 또는 아래 줄 버튼·넓은 칸까지 화면 전체(세 줄). 칸 사이 테두리 폭까지 계산해 선이 이어지게
CAM_GAP = 40  # 칸 사이 테두리를 화면 픽셀로 환산한 폭 (대략값)
PITCH = SIZE + CAM_GAP  # 칸 하나 + 테두리
WIDE_X = 3 * PITCH  # 넓은 칸이 시작하는 x (아래 줄 네 번째 칸 자리)
CAM_W = max(SIZE * 5 + CAM_GAP * 4, WIDE_X + WIDE[0])
CAM_SPAN = 0.22  # 슬로우 모션 화면 가로에 보이는 경주 거리 (전체 = 1)
CAM_START = 0.9  # 선두가 이 지점을 지나면 슬로우 모션 시작
CAM_SPEED = 0.3  # 슬로우 모션 속도 (1 = 보통)
CAM_FINISH_AT = (3 * PITCH + SIZE / 2) / CAM_W  # 카메라가 멈췄을 때 결승선 위치: 4번째 열 한가운데 (테두리에 걸리지 않게)
RUN_LEFT, RUN_SPAN = -0.13, 1.265  # 두 줄 화면: 출발 게이트부터 결승선(5번째 열 가운데)까지 한눈에
# 줄 수별 배치: (화면 높이, 관중석 높이, 첫 레인 y, 레인 간격, 말 크기)
VIEW = {2: (SIZE * 2 + CAM_GAP, 64, 140, 64, 84), 3: (SIZE * 3 + CAM_GAP * 2, 96, 222, 100, 150)}


@lru_cache(maxsize=1)
def _cam_crowd() -> Image.Image:
    rnd = random.Random(3)
    img = Image.new("RGB", (CAM_W * 2, 100), (26, 30, 46))
    d = ImageDraw.Draw(img)
    for _ in range(1300):
        x, y = rnd.randrange(img.width), rnd.randrange(6, 96)
        r = rnd.randrange(4, 8)
        d.ellipse((x - r, y - r, x + r, y + r), fill=rnd.choice([(247, 118, 142), (122, 162, 247), (224, 175, 104),
                                                                  (158, 206, 106), (235, 235, 245), (187, 154, 247)]))
    return img


def race_view(pos: list[float], cam_left: float, span: float, rows: int, anim: int, mine: tuple[int, ...],
              gate: bool = False, flash: float = 0.0, winner: int | None = None, caption: str = "",
              label: str = "") -> Image.Image:
    """경주로를 큰 화면 하나로 그린다 (칸 사이 테두리 포함 좌표)."""
    H, crowd_h, lane0, lane_dy, hsize = VIEW[rows]
    lanes = [lane0 + k * lane_dy for k in range(5)]
    sc = CAM_W / span
    wx = lambda p: (p - cam_left) * sc  # noqa: E731  경주 위치 → 화면 x
    img = Image.new("RGB", (CAM_W, H), (176, 128, 82))
    d = ImageDraw.Draw(img)
    crowd = _cam_crowd()
    off = int(cam_left * sc * 0.35) % (crowd.width - CAM_W)  # 관중석은 천천히 흘러간다 (원근감)
    img.paste(crowd.crop((off, 100 - crowd_h, off + CAM_W, 100)), (0, 0))
    if anim % 2:  # 관중석 카메라 플래시
        rnd = random.Random(anim)
        for _ in range(16):
            x, y = rnd.randrange(CAM_W), rnd.randrange(8, crowd_h - 6)
            d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(255, 255, 230))
    d.rectangle((0, crowd_h, CAM_W, crowd_h + 14), fill=(240, 240, 245))  # 안쪽 난간
    step = 0.01 if span < 0.5 else 0.05
    for k in range(int(cam_left / step) - 1, int((cam_left + span) / step) + 2):  # 난간 기둥 (거리감)
        x = wx(k * step)
        d.rectangle((x, crowd_h, x + 6, crowd_h + 26), fill=(220, 220, 228))
    rnd = random.Random(int(cam_left * 400) + rows)
    for _ in range(int(CAM_W * H / 2400)):  # 흙 질감
        x, y = rnd.randrange(CAM_W), rnd.randrange(crowd_h + 26, H - 20)
        d.ellipse((x, y, x + 3, y + 2), fill=(150, 104, 64))
    for y in lanes:
        d.line((0, y + 6, CAM_W, y + 6), fill=(160, 114, 72), width=3)
    d.rectangle((0, H - 18, CAM_W, H), fill=(240, 240, 245))  # 바깥 난간
    fx = wx(1.0)  # 결승선
    if -40 < fx < CAM_W + 40:
        sq = 16 if rows == 3 or span < 0.5 else 12
        for y in range(crowd_h + 14, H - 18, sq):
            for c in range(2):
                d.rectangle((fx + c * sq, y, fx + c * sq + sq - 1, y + sq - 1),
                            fill=(20, 20, 24) if (y // sq + c) % 2 else (245, 245, 245))
        d.rectangle((fx + sq // 2, 0, fx + sq + sq // 2, crowd_h + 14), fill=(230, 60, 70))
    if gate:  # 출발 게이트
        gx = wx(0.0) + 8
        d.rectangle((gx, crowd_h + 10, gx + 14, H - 16), fill=(90, 94, 110))
        for y in lanes:
            d.rectangle((gx, y - lane_dy + 10, gx + 14, y + 4), fill=(200, 204, 214))
    for i in range(5):  # 위 레인부터 그려서 아래(앞쪽) 말이 위에 겹치게
        x, y = wx(min(pos[i], 1.06)), lanes[i]
        if x < -hsize * 1.5 or x > CAM_W + hsize * 1.5:
            continue
        run = 0.0 < pos[i] < 1.06
        big = hsize / 84
        if run:
            for k in range(4):  # 속도선
                ly = y - hsize * 0.28 - k * hsize * 0.12
                ln = (40 + ((anim + i + k) % 3) * 22) * big
                d.line((x - hsize - ln, ly, x - hsize, ly), fill=(214, 182, 146), width=max(2, int(3 * big)))
            for k in range(4):  # 흙먼지
                r = (10 - k * 2) * big
                dx = hsize * 1.25 + (k * 18 + ((anim + i + k) % 3) * 6) * big
                d.ellipse((x - dx - r, y - 6 - r - k * 4, x - dx + r, y - 6 + r - k * 4), fill=(222, 190, 150))
        hop = (int(-5 * big) if (anim + i) % 2 else int(2 * big)) if run else 0
        h = _horse(hsize, (anim + i) % 2 if run else 0)
        img.paste(h, (int(x - h.width), int(y - h.height + hsize * 0.1 + hop)), h)
        br = int(15 * big) + 2
        bx, by = int(x - h.width - br + 4), int(y - hsize * 0.28 + hop)
        if i in mine:
            d.ellipse((bx - br - 5, by - br - 5, bx + br + 5, by + br + 5), fill=(250, 210, 60))
        d.ellipse((bx - br, by - br, bx + br, by + br), fill=_rgb(HORSE_COLORS[i]), outline=(25, 25, 30), width=2)
        d.text((bx, by + 1), str(i + 1), font=_kr(int(br * 1.3), 6), fill=(20, 20, 28), anchor="mm")
        if winner == i:
            _paste_center(img, _emoji("👑", int(br * 2.4)), bx - int(br * 2.5), by)
    if span < 0.5:  # 슬로우 모션: 가장자리를 어둡게 (집중 효과)
        vig = Image.new("L", (CAM_W, H), 0)
        vd = ImageDraw.Draw(vig)
        for k in range(12):
            vd.rectangle((k * 6, k * 4, CAM_W - k * 6, H - k * 4), outline=150 - k * 12, width=6)
        img = Image.composite(Image.new("RGB", img.size, (10, 10, 14)), img, vig)
    if flash > 0:
        img = Image.blend(img, Image.new("RGB", img.size, (255, 255, 255)), min(1.0, flash))
    if rows == 3:  # 아래 줄: 왼쪽 칸에 슬로우 모션 표시, 넓은 칸 자리에 중계 자막
        d = _Draw(img)
        y0 = 2 * PITCH
        if label and (anim % 10 < 6 or winner is not None):
            d.rounded_rectangle((14, y0 + 120, 182, y0 + 168), 12, fill=(230, 60, 70))
            d.text((98, y0 + 144), label, font=_kr(24, 6), fill=(255, 255, 255), anchor="mm")
        if caption:
            box = Image.new("RGBA", (WIDE[0] - 20, 64), (12, 12, 18, 190))
            img.paste(box, (WIDE_X + 10, y0 + WIDE[1] - 78), box)
            size = 30
            while size > 18 and d.textlength(caption, font=_kr(size, 6)) > WIDE[0] - 40:
                size -= 2
            d.text((WIDE_X + WIDE[0] // 2, y0 + WIDE[1] - 46), caption, font=_kr(size, 6), fill=(255, 236, 140),
                   anchor="mm")
    return img


def view_split(img: Image.Image, rows: int) -> tuple[dict[int, bytes], bytes | None]:
    """큰 화면을 칸별 PNG 로 자르기 (테두리 자리는 버린다). 세 줄이면 아래 줄 세 칸과 넓은 칸까지."""
    tiles = {}
    for r in range(2):
        for c in range(5):
            tiles[r * 5 + c] = _png(img.crop((c * PITCH, r * PITCH, c * PITCH + SIZE, r * PITCH + SIZE)))
    if rows < 3:
        return tiles, None
    y = 2 * PITCH
    for c in range(3):
        tiles[10 + c] = _png(img.crop((c * PITCH, y, c * PITCH + SIZE, y + SIZE)))
    return tiles, _png(img.crop((WIDE_X, y, WIDE_X + WIDE[0], y + WIDE[1])))


@lru_cache(maxsize=64)
def horse_card(no: int, name: str, odds: float, state: str = "", sub: str = "") -> bytes:
    """아랫줄 말 카드. state: '' | mine(고른 말) | win(우승) | mine_win | dim"""
    img = Image.new("RGB", (SIZE, SIZE), (13, 14, 20))
    d = _Draw(img)
    col = _rgb(HORSE_COLORS[no - 1])
    gold = (250, 210, 60)
    bg = (40, 34, 14) if "win" in state else ((34, 36, 54) if state != "dim" else (22, 23, 30))
    edge = gold if ("mine" in state or "win" in state) else (60, 64, 82)
    d.rounded_rectangle((6, 6, 189, 189), 22, fill=bg, outline=edge, width=7 if edge == gold else 2)
    d.ellipse((18, 18, 70, 70), fill=col)
    d.text((44, 45), str(no), font=_kr(32, 6), fill=(20, 20, 28), anchor="mm")
    _paste_center(img, _emoji("🐎", 54).transpose(Image.FLIP_LEFT_RIGHT), 132, 46)
    d.text((98, 104), name, font=_kr(32 if len(name) <= 2 else 26, 6), fill=(236, 238, 248), anchor="mm")
    d.text((98, 146), f"{odds:g}배", font=_kr(30, 6), fill=gold if odds >= 4 else (192, 202, 245), anchor="mm")
    if sub:
        d.text((98, 174), sub, font=_kr(18, 4), fill=gold if "mine" in state or "win" in state else (150, 156, 180),
               anchor="mm")
    return _png(img)


def bet_chip(track_png: bytes, amount: int, selected: bool) -> bytes:
    """대기 중 경주로 칸 위에 띄우는 베팅액 칩 (뒤로 경주로가 비쳐 보이게)."""
    img = Image.open(io.BytesIO(track_png)).convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    gold = (250, 210, 60)
    od.ellipse((48, 48, 148, 148), fill=(*gold, 245) if selected else (20, 22, 32, 200),
               outline=(255, 255, 255, 230) if selected else (*gold, 220), width=5)
    for a in range(0, 360, 45):  # 칩 테두리 무늬
        x, y = 98 + 44 * math.cos(math.radians(a)), 98 + 44 * math.sin(math.radians(a))
        od.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(255, 255, 255, 200) if selected else (*gold, 160))
    img = Image.alpha_composite(img, over).convert("RGB")
    d = _Draw(img)
    tc = (20, 20, 28) if selected else (240, 242, 250)
    d.text((98, 92), str(amount), font=_kr(42, 6), fill=tc, anchor="mm")
    d.text((98, 126), "코인", font=_kr(16, 4), fill=tc, anchor="mm")
    return _png(img)


def kind_chip(track_png: bytes, exacta: bool) -> bytes:
    """두 마리를 골랐을 때 0번 칸 위에 띄우는 승식 전환 단추 (복승 ⇄ 쌍승)."""
    img = Image.open(io.BytesIO(track_png)).convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(over).rounded_rectangle((14, 40, 182, 156), 22, fill=(20, 22, 32, 215),
                                           outline=(250, 210, 60, 230), width=4)
    img = Image.alpha_composite(img, over).convert("RGB")
    d = _Draw(img)
    gold, dim = (250, 210, 60), (130, 136, 160)
    d.text((98, 72), "복승", font=_kr(30, 6), fill=dim if exacta else gold, anchor="mm")
    d.text((98, 98), "⇅", font=_kr(20, 4), fill=(200, 204, 220), anchor="mm")
    d.text((98, 126), "쌍승", font=_kr(30, 6), fill=gold if exacta else dim, anchor="mm")
    return _png(img)


# ---------- 게임 상태 ----------
class Games:
    """mode: menu | mole | simon | pairs | slot. phase: play | show | input | over"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.rnd = random.Random()
        self.mode = "menu"
        self.phase = ""
        self.best = self._load()
        self.score = 0
        self.new_best = False
        # 두더지
        self.end_at = 0.0
        self.holes: dict[int, tuple[str, float]] = {}  # 칸 -> (상태, 사라지는 시각)
        self.next_pop = 0.0
        # 순서 기억
        self.seq: list[int] = []
        self.pos = 0
        self.show_at = 0.0
        self.lit: int | None = None
        self.lit_until = 0.0
        self.over_at = 0.0
        self.wrong: int | None = None
        # 짝 맞추기
        self.cards: list[str] = []
        self.matched: set[int] = set()
        self.open: list[int] = []  # 지금 뒤집혀 있는 (아직 안 맞춘) 카드
        self.flip_back = 0.0  # 틀린 한 쌍을 다시 덮는 시각
        self.peek_until = 0.0  # 시작할 때 잠깐 전부 보여주기
        self.started = 0.0
        # 슬롯머신
        self.coins = int(self.best.get("slot_coins", SLOT_START)) or SLOT_START
        self.reels = [self.rnd.choice(SLOT_SYMBOLS) for _ in SLOT_REELS]
        self.spinning = [False, False, False]
        self.spin_next = 0.0
        self.spin_auto = 0.0  # 이 시각이 지나면 남은 릴 자동 정지
        self.win = 0
        self.win_until = 0.0
        # 블랙잭
        self.bet = 2
        self.bet_now = 0  # 이번 판에 실제로 건 코인 (더블이면 두 배)
        self.shoe: list[tuple[str, str]] = []
        self.dealer: list[tuple[str, str]] = []
        self.player: list[tuple[str, str]] = []
        self.hole = True  # 딜러 두 번째 카드를 가렸는지
        self.result = ""  # win | lose | push | bj
        self.next_draw = 0.0
        # 비디오 포커
        self.hand: list[tuple[str, str]] = []
        self.opp: list[tuple[str, str]] = []  # 상대(컴퓨터) 패
        self.opp_swapped = 0
        self.held = [False] * 5
        self.poker_cmp = 0  # 1 이김, 0 비김, -1 짐
        # 경마
        self.race_names: list[str] = []
        self.race_power: list[float] = []
        self.race_odds: list[float] = []  # 말별 단승 배당
        self.race_book: dict = {}  # 승식별 배당
        self.race_exacta = False  # 두 마리를 골랐을 때 쌍승(순서대로)인지
        self.race_pick: list[int] = []  # 고른 말 (1~3마리)
        self.race_frames: list[list[float]] = []
        self.race_order: list[int] = []
        self.race_start = 0.0
        self.race_t = 0.0  # 경주 시간 (장면 단위, 소수점 = 장면 사이 보간). 슬로우 모션 때 느리게 흐른다
        self.race_last = 0.0
        self.race_cam = ""  # "" | slow(결승 근접 슬로우) | hold(결승 직후 잠깐 멈춤) | after(보통 화면으로 복귀)
        self.race_cam_at = 0.0
        self.race_cam_left = 0.0
        self.race_lead: tuple[int, float] = (-1, 0.0)  # (선두 말, 선두가 바뀐 시각)
        self._race_tiles: tuple[tuple, list[bytes]] | None = None
        self.tycoon = Tycoon(SAVE.parent / "tycoon.json") if Tycoon else None

    @property
    def active(self) -> bool:
        """시간이 흐르는 중인지 (게임 루프·화면보호기 판단용). 슬롯은 돌거나 당첨 연출 중일 때만."""
        if self.mode == "tycoon" and self.tycoon:
            return self.tycoon.active
        if self.mode == "slot":
            return any(self.spinning) or time.time() < self.win_until
        if self.mode == "bj":
            return self.phase == "dealer" or time.time() < self.win_until
        if self.mode == "poker":
            return self.phase == "opp" or time.time() < self.win_until
        if self.mode == "race":
            return self.phase in ("gate", "run") or time.time() < self.win_until
        return self.mode != "menu" and self.phase != "over"

    # ---- 저장 ----
    def _load(self) -> dict:
        try:
            return {"mole": 0, "simon": 0, "pairs": 0, "slot": 0, **json.loads(SAVE.read_text())}
        except Exception:
            return {"mole": 0, "simon": 0, "pairs": 0, "slot": 0}

    def _save(self) -> None:
        try:
            SAVE.parent.mkdir(parents=True, exist_ok=True)
            SAVE.write_text(json.dumps(self.best))
        except Exception:
            pass

    def best_text(self, mode: str) -> str:
        v = self.best.get(mode, 0)
        if mode == "pairs":
            return f"최고 {v}번" if v else "기록 없음"
        if mode in ("slot", "bj", "poker", "race"):
            return f"코인 {self.coins}"
        return f"최고 {v}"

    def _finish(self) -> None:
        self.phase, self.over_at = "over", time.time()
        self.holes.clear()
        if self.mode == "slot":  # 슬롯은 코인 기록을 따로 저장
            self.new_best = False
            return
        old = self.best.get(self.mode, 0)
        if self.mode in LOWER_IS_BETTER:
            self.new_best = self.score > 0 and (old == 0 or self.score < old)
        else:
            self.new_best = self.score > old
        if self.new_best:
            self.best[self.mode] = self.score
            self._save()

    # ---- 입력 ----
    def menu(self) -> None:
        with self.lock:
            self.mode, self.phase, self.holes, self.lit = "menu", "", {}, None

    def press(self, idx: int) -> None:
        """판(0~9) 또는 넓은 칸(13 이상)을 누른 순간."""
        with self.lock:
            now = time.time()
            if self.mode == "menu":
                if idx < len(GAMES):
                    play("tap")
                    self.start(GAMES[idx])
                return
            if self.phase == "over":
                if now - self.over_at > 0.8:  # 끝난 직후 실수로 누른 건 무시
                    self.start(self.mode) if idx < BOARD else self.menu()
                return
            if self.mode == "bj":
                self._press_bj(idx, now)
                return
            if self.mode == "poker":
                self._press_poker(idx, now)
                return
            if self.mode == "race":
                self._press_race(idx, now)
                return
            if self.mode == "tycoon" and self.tycoon:
                self.tycoon.press(idx, now)
                return
            if idx >= BOARD:
                return
            if self.mode == "mole":
                kind = self.holes.get(idx, ("empty", 0))[0]
                if kind == "mole":
                    self.score += 1
                    self.holes[idx] = ("hit", now + 0.35)
                    play("hit", 0)
                elif kind == "gold":
                    self.score += 3
                    self.holes[idx] = ("hit", now + 0.35)
                    play("coin", 0)
                elif kind == "bomb":
                    self.score = max(0, self.score - 3)
                    self.holes[idx] = ("boom", now + 0.5)
                    play("boom", 0)
                elif kind == "empty":
                    self.holes[idx] = ("miss", now + 0.25)
                    play("tap")
            elif self.mode == "pairs":
                self._press_card(idx, now)
            elif self.mode == "slot":
                self._press_slot(idx, now)
            elif self.mode == "simon" and self.phase == "input":
                self.lit, self.lit_until = idx, now + 0.25
                if idx == self.seq[self.pos]:
                    play(f"note{idx}", 0)
                    self.pos += 1
                    if self.pos == len(self.seq):  # 한 판 통과
                        self.score = len(self.seq)
                        self._next_round(now + 0.9)
                else:
                    self.lit = None
                    self.wrong = idx
                    play("bad")
                    self._finish()

    def _press_card(self, idx: int, now: float) -> None:
        if now < self.peek_until or idx in self.matched:
            return
        if len(self.open) == 2:  # 틀린 한 쌍이 아직 보이는 중이면 바로 덮고 진행
            self.open = []
        if idx in self.open:
            return
        self.open.append(idx)
        play("flip", 0)
        if len(self.open) == 2:
            self.score += 1  # 시도 횟수
            a, b = self.open
            if self.cards[a] == self.cards[b]:
                self.matched |= {a, b}
                self.open = []
                play("coin", 0)
                if len(self.matched) == BOARD:
                    play("win", 0)
                    self._finish()
            else:
                self.flip_back = now + 0.9

    def _press_slot(self, idx: int, now: float) -> None:
        if idx in SLOT_LEVERS and not any(self.spinning):
            if self.coins <= 0:
                return
            self.coins -= 1
            self.score += 1  # 돌린 횟수
            play("tap")
            self.spinning = [True, True, True]
            self.spin_next, self.spin_auto, self.win = now, now + 6, 0
            self._save_coins()
        elif idx in SLOT_STOPS or idx in SLOT_REELS:
            k = (SLOT_STOPS.index(idx) if idx in SLOT_STOPS else SLOT_REELS.index(idx))
            if self.spinning[k]:
                self.spinning[k] = False
                play("hit", 0)
                self._after_stop(now)

    def _after_stop(self, now: float) -> None:
        if any(self.spinning):
            return
        a, b, c = self.reels
        if a == b == c:
            self.win = SLOT_PAY[a]
        elif a == b or b == c or a == c:
            self.win = 2
        else:
            self.win = 0
        if self.win:
            self.coins += self.win
            self.win_until = now + (2.4 if self.win >= 30 else 1.4)
            play("jackpot" if self.win >= 30 else ("win" if self.win > 2 else "coin"), 0)
        self._save_coins()
        if self.coins <= 0:
            self._finish()

    # ---- 블랙잭 ----
    def _draw(self) -> tuple[str, str]:
        if len(self.shoe) < 15:  # 카드 2벌을 섞어 쓴다
            self.shoe = [(r, s) for r in RANKS for s in SUITS] * 2
            self.rnd.shuffle(self.shoe)
        return self.shoe.pop()

    def _press_bj(self, idx: int, now: float) -> None:
        if self.phase in ("bet", "done"):
            if idx == BJ_STAND and self.phase == "bet":
                self.bet = BJ_BETS[(BJ_BETS.index(self.bet) + 1) % len(BJ_BETS)] if self.bet in BJ_BETS else 1
            elif idx == BJ_HIT or (self.phase == "done" and idx < BOARD):
                self._deal(now)
            elif idx == BJ_STAND:
                self.phase = "bet"
            return
        if self.phase != "play":
            return
        if idx == BJ_HIT:
            play("card", 0)
            self.player.append(self._draw())
            if hand_value(self.player)[0] >= 21:
                self._dealer_turn(now)
        elif idx == BJ_STAND:
            self._dealer_turn(now)
        elif idx >= 13 and len(self.player) == 2 and self.coins >= self.bet:  # 넓은 칸 = 더블
            self.coins -= self.bet
            self.bet_now *= 2
            self.player.append(self._draw())
            self._dealer_turn(now)

    def _deal(self, now: float) -> None:
        if self.coins <= 0:  # 다 잃었으면 다시 채워 주기
            self.coins = SLOT_START
        bet = min(self.bet, self.coins)
        self.coins -= bet
        self.bet_now = bet
        self.player = [self._draw(), self._draw()]
        self.dealer = [self._draw(), self._draw()]
        play("card", 0)
        self.hole, self.result, self.phase = True, "", "play"
        self._save_coins()
        if hand_value(self.player)[0] == 21 or hand_value(self.dealer)[0] == 21:  # 블랙잭이면 바로 결판
            self.hole = False
            self._settle(now)

    def _dealer_turn(self, now: float) -> None:
        self.hole, self.phase, self.next_draw = False, "dealer", now + 0.7
        if hand_value(self.player)[0] > 21:  # 버스트: 딜러는 더 안 뽑는다
            self._settle(now)

    def _settle(self, now: float) -> None:
        p, d = hand_value(self.player)[0], hand_value(self.dealer)[0]
        natural = p == 21 and len(self.player) == 2
        dealer_natural = d == 21 and len(self.dealer) == 2
        if p > 21:
            self.result, pay = "lose", 0
        elif natural and not dealer_natural:
            self.result, pay = "bj", self.bet_now + (self.bet_now * 3) // 2  # 3:2
        elif dealer_natural and not natural:
            self.result, pay = "lose", 0
        elif d > 21 or p > d:
            self.result, pay = "win", self.bet_now * 2
        elif p == d:
            self.result, pay = "push", self.bet_now
        else:
            self.result, pay = "lose", 0
        self.coins += pay
        self.win = pay - self.bet_now
        self.phase = "done"
        play({"bj": "jackpot", "win": "win", "lose": "lose"}.get(self.result, "tap"), 0)
        if self.result in ("win", "bj"):
            self.win_until = now + 1.6
        self._save_coins()

    # ---- 포커 대결 (5장 드로우, 컴퓨터와 1:1) ----
    def _press_poker(self, idx: int, now: float) -> None:
        """윗줄 = 상대 카드, 아랫줄 = 내 카드(눌러서 킵). 넓은 칸 = 교체.
        대기 중엔 아랫줄이 베팅액(1·2·5·10)과 딜, 끝난 뒤엔 아무 칸 = 같은 베팅으로 다음 판, 넓은 칸 = 베팅 바꾸기."""
        if self.phase == "play":
            if 5 <= idx < BOARD:
                self.held[idx - 5] = not self.held[idx - 5]
                play("tap")
            elif idx >= 13:
                play("card", 0)
                self._poker_draw(now)
            return
        if self.phase == "done":
            if idx >= 13:
                self.phase = "bet"
            elif idx < BOARD:
                self._poker_deal()
            return
        if self.phase == "bet":
            if 5 <= idx <= 8:
                self.bet = BJ_BETS[idx - 5]
            elif idx == 9 or idx >= 13:
                self._poker_deal()

    def _poker_deal(self) -> None:
        if self.coins <= 0:
            self.coins = SLOT_START
        self.shoe = [(r, s) for r in RANKS for s in SUITS]  # 매 판 새 카드 한 벌
        self.rnd.shuffle(self.shoe)
        self.bet_now = min(self.bet, self.coins)
        self.coins -= self.bet_now
        self.hand = [self.shoe.pop() for _ in range(5)]
        self.opp = [self.shoe.pop() for _ in range(5)]
        play("card", 0)
        self.held, self.phase, self.opp_swapped, self.poker_cmp = [False] * 5, "play", 0, 0
        self._save_coins()

    def _poker_draw(self, now: float) -> None:
        self.hand = [c if h else self.shoe.pop() for c, h in zip(self.hand, self.held)]
        keep = poker_ai_holds(self.opp)
        self.opp_swapped = keep.count(False)
        self.opp = [c if k else self.shoe.pop() for c, k in zip(self.opp, keep)]
        self.phase, self.next_draw = "opp", now + 0.9  # 상대가 바꾸는 동안 잠깐 뜸 들이기

    def _poker_showdown(self, now: float) -> None:
        me, op = poker_rank(self.hand), poker_rank(self.opp)
        self.poker_cmp = (me > op) - (me < op)
        mult = 1
        if self.poker_cmp > 0:
            mult = POKER_BONUS.get(me[0], 1)
            pay = self.bet_now * (1 + mult)
            self.win_until = now + (2.4 if mult >= 25 else 1.4)
        elif self.poker_cmp == 0:
            pay = self.bet_now
        else:
            pay = 0
        self.coins += pay
        self.win = pay - self.bet_now
        self.phase = "done"
        play(("jackpot" if mult >= 25 else "win") if self.poker_cmp > 0 else ("tap" if self.poker_cmp == 0 else "lose"), 0)
        self._save_coins()

    # ---- 경마 (말 5마리, 단승 · 복승 · 삼복승) ----
    def _press_race(self, idx: int, now: float) -> None:
        """대기 중: 아랫줄 말을 눌러 고르기/빼기 (1마리 단승, 2마리 복승, 3마리 삼복승),
        윗줄 칩 = 베팅액 1·2·5·10, 넓은 칸 = 출발. 끝난 뒤: 아무 칸 = 다음 경주."""
        if self.phase == "bet":
            if 5 <= idx < BOARD:
                k = idx - 5
                play("tap")
                if k in self.race_pick:
                    self.race_pick.remove(k)
                else:
                    if len(self.race_pick) == 3:  # 네 번째를 고르면 가장 먼저 고른 말을 뺀다
                        self.race_pick.pop(0)
                    self.race_pick.append(k)
            elif idx == RACE_TOGGLE and len(self.race_pick) == 2:
                self.race_exacta = not self.race_exacta
                play("tap")
            elif idx in RACE_CHIPS:
                self.bet = BJ_BETS[RACE_CHIPS.index(idx)]
                play("coin")
            elif idx >= 13 and self.race_pick:
                self._race_go(now)
        elif self.phase == "done" and now - self.over_at > 0.8:
            self._race_card()

    def race_exacta_on(self) -> bool:
        return self.race_exacta and len(self.race_pick) == 2

    def race_kind(self) -> str:
        return "쌍승" if self.race_exacta_on() else BET_TYPES.get(len(self.race_pick), "")

    def race_bet_odds(self) -> float:
        key = tuple(self.race_pick) if self.race_exacta_on() else frozenset(self.race_pick)
        return self.race_book.get(key, 0.0)

    def _race_card(self) -> None:
        """새 경주: 출전마 5마리와 배당 정하기."""
        self.race_names = self.rnd.sample(HORSE_NAMES, 5)
        self.race_power = [self.rnd.uniform(0.975, 1.025) for _ in range(5)]
        self.race_book = race_book(self.race_power, self.rnd)
        self.race_odds = [self.race_book[frozenset([i])] for i in range(5)]
        self.race_frames, self.race_order, self.race_pick = [[0.0] * 5], [], []
        self.phase, self.win, self.race_lead = "bet", 0, (-1, 0.0)

    def _race_go(self, now: float) -> None:
        if self.coins <= 0:
            self.coins = SLOT_START
        self.bet_now = min(self.bet, self.coins)
        self.coins -= self.bet_now
        self._save_coins()
        self.race_frames, self.race_order = race_sim(self.race_power, self.rnd)
        self.phase, self.race_start = "gate", now + 1.5  # 1.5초 출발 대기 (3·2·1)
        play("tap")
        self.race_t, self.race_cam, self.race_cam_left = 0.0, "", 0.0

    def race_hit(self) -> bool:
        n = len(self.race_pick)
        if self.race_exacta_on():
            return self.race_order[:2] == self.race_pick
        return bool(n) and set(self.race_order[:n]) == set(self.race_pick)

    def race_frame(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        if self.phase in ("bet", "gate") or not self.race_frames:
            return 0
        if self.phase == "done":
            return len(self.race_frames) - 1
        return max(0, min(len(self.race_frames) - 1, int(self.race_t)))

    def race_pos(self) -> list[float]:
        """지금 경주 시간의 말 위치 (장면 사이를 보간해 슬로우 모션도 부드럽게)."""
        fr = self.race_frames
        if self.phase != "run":
            return fr[self.race_frame()]
        i = min(int(self.race_t), len(fr) - 1)
        j, a = min(i + 1, len(fr) - 1), self.race_t - int(self.race_t)
        return [p + (q - p) * a for p, q in zip(fr[i], fr[j])]

    def _race_settle(self, now: float) -> None:
        pay = int(self.bet_now * self.race_bet_odds()) if self.race_hit() else 0
        play(("jackpot" if self.race_bet_odds() >= 10 else "win") if pay else "lose", 0)
        self.coins += pay
        self.win = pay - self.bet_now
        self.phase, self.over_at = "done", now
        if pay:
            self.win_until = now + 2.4
        self._save_coins()

    def _save_coins(self) -> None:
        self.best["slot_coins"] = self.coins
        self.best["slot"] = max(self.best.get("slot", 0), self.coins)
        self._save()

    def start(self, mode: str) -> None:
        with self.lock:
            now = time.time()
            self.mode, self.score, self.new_best = mode, 0, False
            self.holes, self.lit = {}, None
            self.wrong = None
            if mode == "mole":
                self.phase, self.end_at, self.next_pop = "play", now + MOLE_SEC, now + 0.6
            elif mode == "pairs":
                self.cards = PAIR_CARDS * 2
                self.rnd.shuffle(self.cards)
                self.matched, self.open = set(), []
                self.phase, self.peek_until, self.started = "play", now + 1.5, now
            elif mode == "race":
                self._race_card()
            elif mode == "tycoon" and self.tycoon:
                self.phase = "play"
                self.tycoon.start()
            elif mode == "poker":
                self.phase, self.hand, self.opp, self.held = "bet", [], [], [False] * 5
            elif mode == "bj":
                self.phase, self.player, self.dealer, self.result = "bet", [], [], ""
                self.bet = min(self.bet, max(1, self.coins)) if self.coins else 2
            elif mode == "slot":
                if self.coins <= 0:  # 다 잃었으면 다시 채워 주기
                    self.coins = SLOT_START
                    self._save_coins()
                self.phase, self.spinning, self.win = "play", [False, False, False], 0
            else:
                self.seq = []
                self._next_round(now + 0.8)

    def _next_round(self, at: float) -> None:
        self._shown = -1
        self.seq.append(self.rnd.randrange(BOARD))
        self.phase, self.pos, self.show_at, self.lit = "show", 0, at, None

    # ---- 시간 진행 (게임 루프에서 호출) ----
    def tick(self) -> None:
        with self.lock:
            now = time.time()
            if self.mode == "mole" and self.phase == "play":
                for i, (k, until) in list(self.holes.items()):
                    if now >= until:
                        del self.holes[i]
                if now >= self.end_at:
                    self._finish()
                    return
                prog = 1 - (self.end_at - now) / MOLE_SEC  # 0 → 1 로 갈수록 빨라짐
                if now >= self.next_pop:
                    free = [i for i in range(BOARD) if i not in self.holes]
                    for _ in range(1 if prog < 0.4 or self.rnd.random() < 0.5 else 2):
                        if not free:
                            break
                        i = free.pop(self.rnd.randrange(len(free)))
                        r = self.rnd.random()
                        kind = "gold" if r < 0.08 else ("bomb" if r < 0.2 and prog > 0.15 else "mole")
                        stay = (1.3 - 0.65 * prog) * (0.75 if kind == "gold" else 1.0)
                        self.holes[i] = (kind, now + stay)
                    self.next_pop = now + self.rnd.uniform(0.45, 0.9) * (1 - 0.45 * prog)
            elif self.mode == "pairs":
                if len(self.open) == 2 and now >= self.flip_back:
                    self.open = []
            elif self.mode == "tycoon" and self.tycoon:
                self.tycoon.tick(now)
            elif self.mode == "race":
                if self.phase == "gate" and now >= self.race_start:
                    self.phase, self.race_t, self.race_last = "run", 0.0, now
                    play("bell", 0)
                    self._gallop_at = now
                if self.phase == "run":
                    speed = {"slow": CAM_SPEED, "hold": 0.0}.get(self.race_cam, 1.0)
                    self.race_t += (now - self.race_last) * RACE_FPS * speed
                    self.race_last = now
                    if self.race_cam in ("", "after") and now - getattr(self, "_gallop_at", 0) > 1.6:
                        self._gallop_at = now  # 말발굽 소리 (슬로우 모션 땐 쉰다)
                        play("gallop", 0, 0.6)
                    f = self.race_frame(now)
                    pos = self.race_pos()
                    need = min(5, max(2, len(self.race_pick)))  # 승식에 필요한 착순까지 들어오면 슬로우 끝
                    if self.race_cam == "" and max(pos) >= CAM_START:
                        self.race_cam, self.race_cam_at = "slow", now
                        play("whoosh", 0)
                        self.race_cam_left = max(pos) - CAM_SPAN * 0.62
                    elif self.race_cam == "slow":
                        self.race_cam_left = max(self.race_cam_left, min(max(pos) - CAM_SPAN * 0.62, 1.0 - CAM_SPAN * CAM_FINISH_AT))
                        if sorted(pos)[-need] >= 1.0:
                            self.race_cam, self.race_cam_at = "hold", now
                            play("shutter", 0)
                            play("cheer", 0, 0.8)
                    elif self.race_cam == "hold" and now - self.race_cam_at > 0.9:
                        self.race_cam = "after"
                    lead = max(range(5), key=lambda i: pos[i])
                    if lead != self.race_lead[0]:
                        self.race_lead = (lead, now)
                    if f >= len(self.race_frames) - 1:
                        self._race_settle(now)
            elif self.mode == "poker":
                if self.phase == "opp" and now >= self.next_draw:
                    self._poker_showdown(now)
            elif self.mode == "bj":
                if self.phase == "dealer" and now >= self.next_draw:
                    if hand_value(self.dealer)[0] < 17:  # 딜러는 16 이하면 뽑고 17 이상이면 멈춘다
                        self.dealer.append(self._draw())
                        play("card", 0)
                        self.next_draw = now + 0.7
                    else:
                        self._settle(now)
            elif self.mode == "slot":
                if any(self.spinning) and now >= self.spin_next:
                    for k, on in enumerate(self.spinning):
                        if on:
                            i = SLOT_SYMBOLS.index(self.reels[k])
                            self.reels[k] = SLOT_SYMBOLS[(i + 1 + k) % len(SLOT_SYMBOLS)]
                    play("tick", 0.1, 0.5)
                    self.spin_next = now + 0.13
                    if now >= self.spin_auto:  # 너무 오래 안 누르면 자동 정지
                        self.spinning = [False, False, False]
                        self._after_stop(now)
            elif self.mode == "simon":
                if self.phase == "show" and now >= self.show_at:
                    # 순서 보여주기: 칸마다 켜짐(on) → 꺼짐(gap)
                    on = max(0.32, 0.6 - 0.02 * len(self.seq))
                    step = on + 0.22
                    k = int((now - self.show_at) / step)
                    if k >= len(self.seq):
                        self.phase, self.lit = "input", None
                    else:
                        lit = self.seq[k] if (now - self.show_at) - k * step < on else None
                        if lit is not None and (self.lit is None or k != getattr(self, "_shown", -1)):
                            self._shown = k
                            play(f"note{lit}", 0)
                        self.lit = lit
                elif self.phase == "input" and self.lit is not None and now >= self.lit_until:
                    self.lit = None

    # ---- 그리기 ----
    def tiles(self) -> dict[int, bytes]:
        with self.lock:
            if self.mode == "menu":
                out = {i: blank_tile() for i in range(BOARD)}
                for c, g in enumerate(GAMES):
                    out[c] = (self.tycoon.menu_tile() if g == "tycoon" and self.tycoon else menu_tile(g, self.best_text(g)))
                return out
            now = time.time()
            if self.mode == "pairs":
                out = {}
                for i in range(BOARD):
                    face = self.cards[i]
                    if i in self.matched:
                        out[i] = card_tile(face, "done")
                    elif now < self.peek_until or i in self.open:
                        out[i] = card_tile(face, "wrong" if len(self.open) == 2 and i in self.open else "up")
                    else:
                        out[i] = card_tile(None, "down")
                return out
            if self.mode == "race":
                return self._race_tiles_now(now)
            if self.mode == "tycoon" and self.tycoon:
                return self.tycoon.tiles()
            if self.mode == "poker":
                out = {}
                glow_on = now < self.win_until and int(now * 5) % 2 == 0
                done = self.phase == "done"
                me_g = "win" if done and self.poker_cmp > 0 and (glow_on or now >= self.win_until) else \
                    ("lose" if done and self.poker_cmp < 0 else "")
                op_g = "win" if done and self.poker_cmp < 0 else ("lose" if done and self.poker_cmp > 0 else "")
                for k in range(5):  # 윗줄: 상대
                    show = self.opp and (done or k in POKER_OPEN)
                    out[k] = play_card(self.opp[k], op_g) if show else play_card(None)
                if self.phase == "bet" or not self.hand:
                    for k in range(4):
                        out[5 + k] = bj_button(str(BJ_BETS[k]), "코인 걸기", "#7dcfff", self.bet == BJ_BETS[k])
                    out[9] = bj_button("딜", f"{min(self.bet, max(self.coins, 1))}코인", "#9ece6a")
                    return out
                for k in range(5):  # 아랫줄: 나
                    c = self.hand[k]
                    out[5 + k] = held_card(c) if self.phase == "play" and self.held[k] else play_card(c, me_g)
                return out
            if self.mode == "bj":
                pg = {"win": "win", "bj": "win", "lose": "lose"}.get(self.result, "")
                dg = {"win": "lose", "bj": "lose", "lose": "win"}.get(self.result, "")
                dealer = [self.dealer[0], None] + self.dealer[2:] if self.hole and self.dealer else self.dealer
                out = {}
                for k, cards in enumerate(_layout(dealer)):
                    out[k] = hand_tile(cards, dg)
                for k, cards in enumerate(_layout(self.player)):
                    out[5 + k] = hand_tile(cards, pg)
                if self.phase == "play":
                    out[BJ_HIT] = bj_button("HIT", "한 장 더", "#9ece6a")
                    out[BJ_STAND] = bj_button("STAND", "그만", "#f7768e")
                elif self.phase == "dealer":
                    out[BJ_HIT] = bj_button("HIT", "딜러 차례", "#9ece6a", False)
                    out[BJ_STAND] = bj_button("STAND", "", "#f7768e", False)
                else:
                    out[BJ_HIT] = bj_button("딜", f"{min(self.bet, max(self.coins, 1))}코인 걸기", "#e0af68")
                    out[BJ_STAND] = bj_button(f"{self.bet}", "베팅 바꾸기", "#7dcfff") if self.phase == "bet" \
                        else bj_button("베팅", "바꾸기", "#7dcfff")
                return out
            if self.mode == "slot":
                glow = now < self.win_until and int(now * 5) % 2 == 0
                spinning = any(self.spinning)
                out = {i: blank_tile() for i in range(BOARD)}
                for k, (r, st) in enumerate(zip(SLOT_REELS, SLOT_STOPS)):
                    out[r] = reel_tile(self.reels[k], glow, self.spinning[k])
                    out[st] = slot_button("stop" if self.spinning[k] else "stopped")
                for i in SLOT_LEVERS:
                    out[i] = slot_button("wait" if spinning or self.coins <= 0 else "lever")
                return out
            if self.mode == "mole":
                return {i: mole_tile(self.holes.get(i, ("empty", 0))[0]) for i in range(BOARD)}
            wrong = self.wrong
            out = {}
            for i in range(BOARD):
                if self.phase == "over":
                    answer = self.seq[self.pos] if self.pos < len(self.seq) else None
                    out[i] = simon_tile(i, i == answer, "✕" if i == wrong else ("!" if i == answer else ""))
                else:
                    out[i] = simon_tile(i, i == self.lit)
            return out

    def _race_ranks(self, f: int) -> list[int]:
        """장면 f 의 순위 (말 번호 0~4 를 앞선 순서로). 끝났으면 실제 착순."""
        if self.phase == "done":
            return self.race_order
        pos = self.race_frames[f]
        return sorted(range(5), key=lambda i: -pos[i])

    def _race_tiles_now(self, now: float) -> dict[int, bytes]:
        if self.phase in ("gate", "run"):
            return self._race_big(now)[0]
        f = self.race_frame(now)
        blink = self.phase == "done" and now < self.win_until and int(now * 5) % 2 == 0
        picks = tuple(self.race_pick)
        key = (f, self.phase, picks, blink, tuple(self.race_names), self.bet, self.race_exacta_on())
        if self._race_tiles and self._race_tiles[0] == key:  # 같은 장면이면 다시 그리지 않는다
            return dict(enumerate(self._race_tiles[1]))
        done = self.phase == "done"
        winner = self.race_order[0] if done else None
        tiles = race_track(self.race_frames[f], f, self.phase in ("bet", "gate"), picks, winner)
        if self.phase == "bet":  # 윗줄 빈 경주로 위에 베팅액 칩
            for c, k in enumerate(RACE_CHIPS):
                tiles[k] = bet_chip(tiles[k], BJ_BETS[c], self.bet == BJ_BETS[c])
            if len(picks) == 2:
                tiles[RACE_TOGGLE] = kind_chip(tiles[RACE_TOGGLE], self.race_exacta_on())
        ranks = self._race_ranks(f)
        n = len(picks)
        for k in range(5):
            mine = k in picks
            if self.phase == "bet":
                if not mine:
                    state, sub = "", ""
                elif self.race_exacta_on():
                    state, sub = "mine", f"{picks.index(k) + 1}착 예상"
                else:
                    state, sub = "mine", (f"{picks.index(k) + 1}번째 선택" if n > 1 else "선택")
            elif self.phase == "gate":
                state, sub = ("mine" if mine else ""), ("내 말" if mine else "")
            elif self.phase == "run":
                state, sub = ("mine" if mine else ""), f"{ranks.index(k) + 1}위"
            else:
                placed = k in self.race_order[:max(n, 1)]  # 맞혀야 하는 자리(1착 / 1·2착 / 1·2·3착)에 든 말
                state = ("mine_win" if mine else "win") if placed and not blink else ("mine" if mine else ("" if placed else "dim"))
                sub = f"{ranks.index(k) + 1}착"
            tiles.append(horse_card(k + 1, self.race_names[k], self.race_odds[k], state, sub))
        self._race_tiles = (key, tiles)
        return dict(enumerate(tiles))

    @property
    def fullscreen(self) -> bool:
        """경마 슬로우 모션: 아래 줄 버튼·넓은 칸까지 화면 전체를 쓰는 중 (대시보드가 아래 줄을 게임에 넘긴다)."""
        if self.mode == "tycoon" and self.tycoon:
            return self.tycoon.fullscreen
        return self.mode == "race" and self.phase == "run" and self.race_cam in ("slow", "hold")

    def _race_big(self, now: float) -> tuple[dict[int, bytes], bytes | None]:
        """출발 대기·경주 중 큰 화면. 보통은 위 두 줄, 결승 직전 슬로우 모션은 화면 전체 (초당 5장면만 새로 그림)."""
        full = self.fullscreen
        picks = tuple(self.race_pick)
        key = ("big", int(now * 5), self.phase, self.race_cam, picks)
        if self._race_tiles and self._race_tiles[0] == key:
            return self._race_tiles[1]
        pos = self.race_pos()
        if full:
            hold = self.race_cam == "hold"
            # 들어갈 때 번쩍 → 슬로우 모션, 결승 통과 순간엔 카메라 셔터처럼 번쩍하고 멈춘 사진 (사진 판정)
            flash = max(0.0, (0.8 if hold else 0.9) - (now - self.race_cam_at) * (4 if hold else 3))
            anim = int(self.race_cam_at * 5) if hold else int(now * 5)
            img = race_view(pos, self.race_cam_left, CAM_SPAN, 3, anim, picks, flash=flash,
                            winner=self.race_order[0] if hold else None, caption=self._race_caption(pos),
                            label="사진 판정" if hold else "슬로우 모션")
            out = view_split(img, 3)
        else:
            img = race_view(pos, RUN_LEFT, RUN_SPAN, 2, int(now * 5), picks, gate=self.phase == "gate")
            out = view_split(img, 2)
        self._race_tiles = (key, out)
        return out

    def _race_caption(self, pos: list[float]) -> str:
        ranks = sorted(range(5), key=lambda i: -pos[i])
        if self.race_cam == "hold":
            w = self.race_order[0]
            return f"{w + 1}번 {self.race_names[w]} 결승선 통과!"
        gap = pos[ranks[0]] - pos[ranks[1]]
        return f"{ranks[0] + 1}번 · {ranks[1] + 1}번 코 차이 접전!" if gap < 0.012 else f"{ranks[0] + 1}번 {self.race_names[ranks[0]]}, 결승선이 눈앞!"

    def _race_wide(self) -> bytes:
        now = time.time()
        if self.fullscreen:
            wide = self._race_big(now)[1]
            if wide:
                return wide
        picks = self.race_pick
        n = len(picks)
        kind = self.race_kind()
        nums = ("→" if self.race_exacta_on() else "·").join(str(i + 1) for i in picks)
        if self.phase == "bet":
            if not picks:
                return wide_panel("경마", str(self.coins), ["아랫줄 말 고르기: 1마리 단승",
                                                         "2마리 복승·쌍승 · 3마리 삼복승",
                                                         "윗줄 칩: 베팅액"], "#ff9e64")
            odds = self.race_bet_odds()
            rule = BET_RULES["exacta" if self.race_exacta_on() else n]
            hint = "왼쪽 위 칸: 복승 ⇄ 쌍승" if n == 2 else "여기를 누르면 출발"
            return wide_panel(f"{kind} {nums}번 · {odds:g}배", "출발",
                              [rule, f"{self.bet}코인 걸기 → 맞히면 {int(self.bet * odds)}코인", hint], "#ff9e64")
        if self.phase == "gate":
            left = max(1, math.ceil(self.race_start - now))
            return wide_panel("출발 준비", str(left), [f"{kind} {nums}번", f"{self.bet_now}코인 · {self.race_bet_odds():g}배"],
                              "#e0af68")
        f = self.race_frame(now)
        ranks = self._race_ranks(f)
        order = " · ".join(str(i + 1) for i in ranks)
        mine = "·".join(str(ranks.index(i) + 1) for i in sorted(picks, key=ranks.index))
        if self.phase == "run" and self.race_cam in ("slow", "hold"):
            pos = self.race_pos()
            ranks = sorted(range(5), key=lambda i: -pos[i])
            mine = "·".join(str(ranks.index(i) + 1) for i in sorted(picks, key=ranks.index))
            top = " · ".join(f"{i + 1}번" for i in ranks[:3])
            if self.race_cam == "hold":
                w = self.race_order[0]
                return wide_panel(f"{w + 1}번 {self.race_names[w]} 결승선 통과!", f"{mine}위", [f"선두 {top}", f"{kind} {nums}번"],
                                  "#e0af68")
            gap = pos[ranks[0]] - pos[ranks[1]]
            head = "결승선 앞, 코 차이 접전!" if gap < 0.012 else "결승선이 눈앞!"
            return wide_panel(head, f"{mine}위", [f"선두 {top}", f"{kind} {nums}번"], "#f7768e")
        if self.phase == "run":
            pos = self.race_frames[f]
            lead = ranks[0]
            lead_name = f"{lead + 1}번 {self.race_names[lead]}"
            gap = pos[ranks[0]] - pos[ranks[1]]
            if f < 5:
                head = "출발했습니다!"
            elif pos[lead] > 0.72 and gap < 0.015:
                head = "마지막 직선, 접전!"
            elif now - self.race_lead[1] < 1.4 and f > 6:
                head = f"{lead_name} 선두로!"
            elif pos[lead] > 0.72:
                head = f"마지막 직선! {lead_name}"
            else:
                head = f"{lead_name} 선두"
            return wide_panel(head, f"{mine}위", [f"순위 {order}", f"{kind} {nums}번"], "#ff9e64", pos[lead])
        w = self.race_order[0]
        won = self.race_hit()
        head = f"{w + 1}번 {self.race_names[w]} 우승!"
        big = f"+{self.win}" if self.win > 0 else str(self.win)
        mine_each = " · ".join(f"{i + 1}번 {ranks.index(i) + 1}착" for i in sorted(picks, key=ranks.index))
        first = f"{kind} 적중! {self.race_bet_odds():g}배" if won else f"{kind}: {mine_each}"
        return wide_panel(head, big, [first, f"착순 {order} · 코인 {self.coins}", "아무 칸: 다음 경주"],
                          "#9ece6a" if won else "#f7768e")

    def wide(self) -> bytes:
        with self.lock:
            best = self.best.get(self.mode, 0)
            if self.mode == "menu":
                return wide_panel("게임", "", ["하고 싶은 게임 칸을 누르세요",
                                              "두더지 · 순서 · 짝 · 슬롯 · 블랙잭 · 포커 · 경마",
                                              "가운데 버튼: 게임 중 메뉴로"], "#9ece6a")
            if self.mode == "race":
                return self._race_wide()
            if self.mode == "tycoon" and self.tycoon:
                return self.tycoon.wide()
            if self.mode == "poker":
                if self.phase in ("play", "opp"):
                    me = POKER_NAMES[poker_rank(self.hand)[0]]
                    if self.phase == "opp":
                        return wide_panel("상대가 바꾸는 중", "…", [f"상대 {self.opp_swapped}장 교체", f"내 패: {me}"],
                                          "#bb9af7")
                    return wide_panel("포커 대결", "교체", ["내 카드를 눌러 킵", "킵 다 고르면 여기 누르기",
                                                        f"내 패: {me} · 베팅 {self.bet_now}코인"], "#e0af68")
                if self.phase == "done":
                    me, op = POKER_NAMES[poker_rank(self.hand)[0]], POKER_NAMES[poker_rank(self.opp)[0]]
                    head = {1: "이겼어요", 0: "비겼어요", -1: "졌어요"}[self.poker_cmp]
                    if self.poker_cmp > 0 and poker_rank(self.hand)[0] >= 4:
                        head = me + "!"
                    big = f"+{self.win}" if self.win > 0 else ("0" if self.win == 0 else str(self.win))
                    color = "#9ece6a" if self.poker_cmp > 0 else ("#7dcfff" if self.poker_cmp == 0 else "#f7768e")
                    return wide_panel(head, big, [f"나 {me} vs 상대 {op}", f"코인 {self.coins}",
                                                  "아무 칸: 다음 판 · 여기: 베팅"], color)
                return wide_panel("포커 대결", str(self.coins), ["컴퓨터와 5장 드로우 포커",
                                                             "이기면 2배 · 스트레이트 이상은 보너스",
                                                             "베팅 고르고 딜"], "#e0af68")
            if self.mode == "bj":
                p = hand_value(self.player)[0] if self.player else 0
                if self.phase == "bet":
                    return wide_panel("블랙잭", str(self.coins), ["오른쪽 위: 딜 · 오른쪽 아래: 베팅 바꾸기",
                                                              f"베팅 {self.bet}코인", "21에 가깝게, 넘으면 짐"], "#bb9af7")
                if self.phase in ("play", "dealer"):
                    shown = hand_value(self.dealer[:1])[0] if self.hole else hand_value(self.dealer)[0]
                    dbl = "넓은 칸: 더블" if self.phase == "play" and len(self.player) == 2 and self.coins >= self.bet_now \
                        else f"코인 {self.coins}"
                    return wide_panel("블랙잭", str(p), [f"딜러 {shown}{'+?' if self.hole else ''} · 나 {p}",
                                                        f"베팅 {self.bet_now}코인", dbl], "#bb9af7")
                d = hand_value(self.dealer)[0]
                head = {"bj": "블랙잭!", "win": "이겼어요", "push": "비겼어요", "lose": "졌어요"}[self.result]
                big = f"+{self.win}" if self.win > 0 else ("0" if self.win == 0 else str(self.win))
                why = "버스트" if p > 21 else ("딜러 버스트" if d > 21 else f"딜러 {d} · 나 {p}")
                return wide_panel(head, big, [why, f"코인 {self.coins}", "아무 칸: 다음 판"],
                                  "#e0af68" if self.result in ("win", "bj") else ("#7dcfff" if self.result == "push" else "#f7768e"))
            if self.mode == "slot":
                if self.phase == "over":
                    return wide_panel("코인을 다 썼어요", "0", ["판 누르기: 20코인으로 다시", "가운데: 메뉴"], "#f7768e")
                if time.time() < self.win_until:
                    head = "잭팟!" if self.win >= 30 else ("당첨!" if self.win > 2 else "두 개 같음")
                    return wide_panel(head, f"+{self.win}", [f"코인 {self.coins}", f"최고 {self.best.get('slot', 0)}"],
                                      "#e0af68")
                hint = "STOP 으로 하나씩 멈추기" if any(self.spinning) else "양쪽 끝 칸: 돌리기 (1코인)"
                return wide_panel("슬롯머신", str(self.coins), [hint, "7 7 7 = 50 · 다이아 30 · 별 15", "두 개 같으면 +2"],
                                  "#ff9e64")
            if self.mode == "pairs" and self.phase != "over":
                secs = int(time.time() - self.started)
                msg = "잘 봐 두세요" if time.time() < self.peek_until else f"맞춘 짝 {len(self.matched) // 2}/5"
                return wide_panel("짝 맞추기", str(self.score), [msg, f"시도 {self.score}번 · {secs}초",
                                                                self.best_text("pairs")], "#73daca")
            if self.phase == "over":
                head = "새 기록!" if self.new_best else ("다 맞췄어요" if self.mode == "pairs" else "게임 끝")
                best_line = self.best_text(self.mode) if self.mode == "pairs" else f"최고 {max(best, self.score)}"
                return wide_panel(head, str(self.score), [best_line, "판 누르기: 다시 하기",
                                                          "가운데: 메뉴"], "#e0af68" if self.new_best else "#f7768e")
            if self.mode == "mole":
                left = max(0.0, self.end_at - time.time())
                return wide_panel("두더지 잡기", str(self.score), [f"남은 시간 {math.ceil(left)}초", f"최고 {best}",
                                                                 "황금 +3 · 폭탄 -3"], "#9ece6a", left / MOLE_SEC)
            msg = "잘 보세요" if self.phase == "show" else f"따라 누르기 {self.pos}/{len(self.seq)}"
            return wide_panel("순서 기억", str(len(self.seq)), [msg, f"최고 {best}"], "#7aa2f7")

    def wide_key(self) -> tuple:
        """넓은 칸이 바뀌었는지 비교할 값 (불필요한 전송 줄이기)."""
        with self.lock:
            sec = math.ceil(self.end_at - time.time()) if self.mode == "mole" and self.phase == "play" else 0
            if self.mode == "pairs" and self.phase == "play":
                sec = int(time.time() - self.started)
            now = time.time()
            return (self.mode, self.phase, self.score, self.pos, len(self.seq), sec, self.new_best, self.coins,
                    any(self.spinning), now < self.win_until, now < self.peek_until, len(self.matched),
                    len(self.player), len(self.dealer), self.hole, self.result, self.bet, tuple(self.held),
                    tuple(self.hand), tuple(self.opp), tuple(self.race_pick), self.race_frame(now) if self.mode == "race" else 0,
                    math.ceil(self.race_start - now) if self.phase == "gate" else 0, tuple(self.race_names),
                    self.tycoon.key() if self.mode == "tycoon" and self.tycoon else None, self.race_cam)

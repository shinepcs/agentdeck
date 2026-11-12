"""Ulanzi D200 직접 제어 드라이버 (공식 앱 불필요).

프로토콜 출처: redphx/strmdck (MIT), jcalado/companion-surface-d200 (USBPcap 분석).
패킷: [7c 7c][cmd:2 BE][length:4 LE][data → 1024 바이트 패딩]
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import string
import threading
import time
import zipfile
from dataclasses import dataclass
from typing import Callable

import hid
from PIL import Image, ImageDraw, ImageFont

from i18n import t

VID, PID = 0x2207, 0x0019
PACKET = 1024
HEADER = 8
COLS, ROWS = 5, 3
BUTTON_COUNT = 13  # 5 + 5 + 3, 마지막 줄 3_2~4_2 는 작은 창(458x196)
ICON = 196

CMD_SET_BUTTONS = 0x0001
CMD_SMALL_WINDOW = 0x0006
CMD_BRIGHTNESS = 0x000A
CMD_LABEL_STYLE = 0x000B
CMD_PARTIAL_UPDATE = 0x000D
SMALL_BACKGROUND = 2  # 작은 창 모드: 배경 이미지
IN_BUTTON = 0x0101
IN_DEVICE_INFO = 0x0303

FONT_PATH = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "malgun.ttf") if os.name == "nt" else "/System/Library/Fonts/AppleSDGothicNeo.ttc"


@dataclass
class InputEvent:
    index: int
    kind: str  # "button" | "encoder"
    action: str  # "press" | "release" | "left" | "right"
    state: int


@dataclass
class Button:
    """버튼 하나의 표시 내용."""

    title: str = ""
    sub: str = ""
    header: str = ""  # 상단 작은 라벨
    bg: str = "#1e1e2e"
    fg: str = "#ffffff"
    accent: str | None = None  # 하단 게이지 색
    ratio: float | None = None  # 0~1 게이지
    # 미니 게이지 여러 개: (라벨, 0~1, 색). 지정하면 sub/ratio 대신 하단에 줄 단위로 그린다
    bars: list[tuple] | None = None
    border: str | None = None  # 강조 테두리 색 (경고 등)
    header_fg: str | None = None  # 헤더 글자색 (없으면 accent)
    raw_header: bool = False
    image: bytes | None = None  # 미리 그린 196x196 PNG (어항 등). 있으면 그대로 보낸다  # 헤더가 사용자 데이터(종목·프로젝트·pane 이름)면 번역하지 않음
    fill: float | None = None  # 0~1: 아래에서부터 칸을 채우는 비율 (타이머)
    fill_color: str = "#f7768e"


def _fit(d: ImageDraw.ImageDraw, text: str, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    """텍스트가 max_w 안에 들어갈 때까지 글자 크기를 줄인다."""
    while size > 12:
        f = ImageFont.truetype(FONT_PATH, size)
        if d.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(FONT_PATH, size)


def _render_bars(d: ImageDraw.ImageDraw, btn: Button) -> None:
    """헤더 + (큰 숫자) + 라벨 붙은 미니 게이지 여러 줄.

    bars 항목: (라벨, 0~1, 색) 또는 (라벨, 0~1, 색, 오른쪽 값 텍스트)
    title 이 비어 있으면 큰 숫자 없이 게이지를 위로 올려 3줄까지 여유 있게 그린다.
    """
    tiny = ImageFont.truetype(FONT_PATH, 22)
    lab = ImageFont.truetype(FONT_PATH, 19)
    if btn.header:
        d.text((ICON / 2, 24), btn.header, font=_fit(d, btn.header, 22, ICON - 20), fill=btn.accent or btn.fg, anchor="mm")
    if btn.title:
        big = ImageFont.truetype(FONT_PATH, 46 if len(btn.title) <= 4 else 34)
        d.text((ICON / 2, 70), btn.title, font=big, fill=btn.fg, anchor="mm")
        y, step = 112, 28
    else:
        y, step = 54, 36
    label_w = max((d.textlength(b[0], font=lab) for b in btn.bars or []), default=0)
    for bar in btn.bars or []:
        label, ratio, color = bar[:3]
        value = bar[3] if len(bar) > 3 else None
        d.text((12, y + 7), label, font=lab, fill="#a9b1d6", anchor="lm")
        x0, x1 = int(12 + label_w + 8), ICON - (52 if value else 14)
        d.rounded_rectangle((x0, y, x1, y + 14), 7, fill="#3a3a4a")
        if ratio is not None and ratio > 0:
            d.rounded_rectangle((x0, y, x0 + (x1 - x0) * min(1.0, ratio), y + 14), 7, fill=color)
        if value:
            d.text((ICON - 10, y + 7), value, font=lab, fill="#c0caf5", anchor="rm")
        y += step
    if btn.sub:
        d.text((ICON / 2, min(y + 10, ICON - 16)), btn.sub, font=lab, fill="#a9b1d6", anchor="mm")


def render_icon(btn: Button) -> bytes:
    """버튼 정보를 196x196 PNG 로 그린다. 문구는 화면 언어(i18n)에 맞춰 바꾼다."""
    from dataclasses import replace

    from i18n import tr

    if btn.image is not None:
        return btn.image
    btn = replace(btn, header=btn.header if btn.raw_header else tr(btn.header), title=tr(btn.title), sub=tr(btn.sub),
                  bars=[(tr(b[0]), *b[1:3], *(tr(x) for x in b[3:])) for b in btn.bars] if btn.bars else None)
    img = Image.new("RGB", (ICON, ICON), btn.bg)
    d = ImageDraw.Draw(img)
    if btn.fill is not None and btn.fill > 0:
        top = int(ICON * (1 - min(1.0, btn.fill)))
        d.rectangle((0, top, ICON, ICON), fill=btn.fill_color)
    if btn.border:
        d.rounded_rectangle((2, 2, ICON - 3, ICON - 3), 18, outline=btn.border, width=5)
    if btn.bars:
        _render_bars(d, btn)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    big = ImageFont.truetype(FONT_PATH, 52 if len(btn.title) <= 5 else 34)
    small = ImageFont.truetype(FONT_PATH, 24)
    tiny = ImageFont.truetype(FONT_PATH, 22)
    if btn.header:
        d.text((ICON / 2, 26), btn.header, font=_fit(d, btn.header, 22, ICON - 20), fill=btn.header_fg or btn.accent or btn.fg, anchor="mm")
    d.text((ICON / 2, 84), btn.title, font=_fit(d, btn.title, big.size, ICON - 16), fill=btn.fg, anchor="mm")
    if btn.sub:
        d.text((ICON / 2, 134), btn.sub, font=_fit(d, btn.sub, small.size, ICON - 14), fill="#a9b1d6" if btn.fg == "#ffffff" else btn.fg, anchor="mm")
    if btn.ratio is not None:
        r = max(0.0, min(1.0, btn.ratio))
        d.rounded_rectangle((16, 160, ICON - 16, 176), 8, fill="#3a3a4a")
        if r > 0:
            d.rounded_rectangle((16, 160, 16 + (ICON - 32) * r, 176), 8, fill=btn.accent or "#7aa2f7")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _frame(cmd: int, length: int, data: bytes) -> bytes:
    if len(data) > PACKET - HEADER:
        raise ValueError("data too large for one frame")
    head = b"\x7c\x7c" + cmd.to_bytes(2, "big") + length.to_bytes(4, "little")
    return (head + data).ljust(PACKET, b"\x00")


def _payload_safe(payload: bytes) -> bool:
    # 펌웨어 버그: 1016 + 1024*N 위치 바이트가 0x00/0x7c 이면 안 됨
    return all(payload[i] not in (0x00, 0x7C) for i in range(PACKET - HEADER, len(payload), PACKET))


def build_zip(buttons: dict[int, Button], small_png: bytes | None = None) -> bytes:
    """manifest.json + 아이콘 PNG 를 ZIP 으로 묶는다 (펌웨어 버그 회피 포함).

    small_png: 오른쪽 아래 넓은 칸(3_2, 458x196) 배경 이미지. 주면 SmallViewMode 2 로 표시된다.
    """
    icons: dict[str, bytes] = {}
    manifest: dict[str, dict] = {}
    for idx, btn in buttons.items():
        col, row = idx % COLS, idx // COLS
        png = render_icon(btn)
        # 장치가 파일명으로 아이콘을 캐시하므로 내용 해시를 이름에 넣어 바뀐 아이콘만 새로 그리게 한다
        name = f"Images/{hashlib.sha1(png).hexdigest()[:16]}.png"
        icons[name] = png
        manifest[f"{col}_{row}"] = {"State": 0, "ViewParam": [{"Icon": name, "Text": ""}]}
    if small_png:
        name = f"Images/{hashlib.sha1(small_png).hexdigest()[:16]}.png"
        icons[name] = small_png
        manifest["3_2"] = {"State": 0, "SmallViewMode": SMALL_BACKGROUND, "ViewParam": [{"Icon": name, "Text": ""}]}

    dummy = ""
    for _ in range(200):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            if dummy:
                z.writestr("dummy.txt", dummy)
            z.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
            for name, data in icons.items():
                z.writestr(name, data)
        payload = buf.getvalue()
        if _payload_safe(payload):
            return payload
        dummy += "".join(random.choices(string.ascii_letters, k=8))
    raise RuntimeError("could not build firmware-safe zip")


class D200:
    def __init__(self) -> None:
        info = next((d for d in hid.enumerate(VID, PID) if d["interface_number"] == 0), None)
        if not info:
            raise RuntimeError(t("D200 을 찾지 못했어요 (USB 연결과 Ulanzi Studio 종료를 확인하세요)",
                                 "D200 not found (check the USB cable and quit Ulanzi Studio)"))
        self.dev = hid.device()
        self.dev.open_path(info["path"])
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.disconnected = threading.Event()
        self._small = "1|0|0|00:00:00|0"
        self.on_event: Callable[[InputEvent], None] | None = None
        self.on_info: Callable[[str], None] | None = None

    # ---- 송신 ----
    def _write(self, packets: list[bytes]) -> None:
        with self._lock:
            for p in packets:
                self.dev.write(b"\x00" + p)  # report ID 0 (번호 없는 리포트)

    def send(self, cmd: int, data: bytes) -> None:
        self._write([_frame(cmd, len(data), data)])

    def set_brightness(self, percent: int) -> None:
        self.send(CMD_BRIGHTNESS, str(max(0, min(100, percent))).encode())

    def set_small_window(self, mode: int = 1, cpu: int = 0, mem: int = 0, gpu: int = 0) -> None:
        """mode: 0=CPU/RAM/GPU 통계, 1=아날로그 시계, 200~203=디지털 시계."""
        self._small = f"{mode}|{cpu}|{mem}|{time.strftime('%H:%M:%S')}|{gpu}"
        self.send(CMD_SMALL_WINDOW, self._small.encode())

    def set_buttons(self, buttons: dict[int, Button], partial: bool = False, small_png: bytes | None = None) -> None:
        payload = build_zip(buttons, small_png)
        cmd = CMD_PARTIAL_UPDATE if partial else CMD_SET_BUTTONS
        first = payload[: PACKET - HEADER]
        packets = [_frame(cmd, len(payload), first)]
        for off in range(PACKET - HEADER, len(payload), PACKET):
            packets.append(payload[off : off + PACKET].ljust(PACKET, b"\x00"))
        self._write(packets)

    # ---- 수신 ----
    def _parse(self, r: bytes) -> None:
        if len(r) < HEADER or r[0] != 0x7C or r[1] != 0x7C:
            return
        cmd = int.from_bytes(r[2:4], "big")
        length = int.from_bytes(r[4:8], "little")
        data = r[HEADER : HEADER + length]
        if cmd == IN_BUTTON and len(data) >= 4:
            kind = "encoder" if data[2] == 0x02 else "button"
            action = {0x01: "press", 0x02: "left", 0x03: "right"}.get(data[3], "release")
            if self.on_event:
                self.on_event(InputEvent(data[1], kind, action, data[0]))
        elif cmd == IN_DEVICE_INFO and self.on_info:
            self.on_info(data.split(b"\x00")[0].decode("ascii", "replace"))

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                r = self.dev.read(PACKET, 100)
            except (OSError, ValueError):
                # USB 분리 등: 끊김 표시 후 종료 (상위에서 프로세스를 끝내면 launchd 가 재시작)
                self.disconnected.set()
                self._stop.set()
                return
            if r:
                self._parse(bytes(r))

    def _keepalive_loop(self) -> None:
        # 앱 연결이 끊긴 걸로 판단하지 않도록 주기적으로 작은 창 데이터를 보낸다
        while not self._stop.wait(5):
            mode = int(self._small.split("|")[0])
            self.set_small_window(mode)

    def start(self) -> None:
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._keepalive_loop, daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        time.sleep(0.2)
        self.dev.close()


if __name__ == "__main__":
    import sys

    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    deck = D200()
    palette = ["#f7768e", "#ff9e64", "#e0af68", "#9ece6a", "#7dcfff", "#7aa2f7", "#bb9af7"]
    buttons = {i: Button(title=f"{i}", sub="눌러봐", bg="#1a1b26", accent=palette[i % 7], ratio=i / 12) for i in range(BUTTON_COUNT)}
    counts = {i: 0 for i in range(BUTTON_COUNT)}

    def handle(ev: InputEvent) -> None:
        print(f"{time.strftime('%H:%M:%S')} {ev}", flush=True)
        if ev.kind == "button" and ev.action == "press" and ev.index in buttons:
            counts[ev.index] += 1
            buttons[ev.index] = Button(title=f"{ev.index}", sub=f"{counts[ev.index]}회", bg=palette[ev.index % 7], fg="#1a1b26")
            deck.set_buttons(buttons)

    deck.on_event = handle
    deck.on_info = lambda s: print("DEVICE INFO:", s, flush=True)
    deck.start()
    deck.set_brightness(80)
    deck.set_buttons(buttons)
    deck.set_small_window(mode=1)
    print(f"=== listening for button events for {duration:.0f}s ===", flush=True)
    try:
        time.sleep(duration)
    finally:
        deck.close()
        print("=== done ===", flush=True)

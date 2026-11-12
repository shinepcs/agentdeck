"""Mirabox HSV293S (6603:1014), using the existing dashboard's 13-key layout.

Protocol/key map: bitfocus/companion-surface-mirabox-stream-dock (MIT),
src/streamdock.ts and src/models/HSV-293S.ts. No firmware changes.
"""
from __future__ import annotations

import io
import threading

import hid
from PIL import Image

from d200 import D200, PACKET, Button, InputEvent, render_icon

VID, PID = 0x6603, 0x1014
KEYS = (13, 10, 7, 4, 1, 14, 11, 8, 5, 2, 15, 12, 9, 6, 3)
PREFIX = b'CRT\0\0'


def command(data: bytes) -> bytes:
    return (PREFIX + data).ljust(PACKET, b'\0')


class Mirabox(D200):
    def __init__(self) -> None:
        info = next((d for d in hid.enumerate(VID, PID) if d['interface_number'] == 0), None)
        if not info:
            raise RuntimeError('Mirabox HSV293S (6603:1014) not found; check USB and quit Stream Dock.')
        self.dev = hid.device()
        self.dev.open_path(info['path'])
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.disconnected = threading.Event()
        self._images: dict[int, bytes] = {}
        self.on_event = None
        self.on_info = None

    def _write(self, packets: list[bytes]) -> None:
        with self._lock:
            try:
                for packet in packets:
                    report = b'\0' + packet
                    if self.dev.write(report) != len(report):
                        raise OSError('Incomplete Mirabox HID write')
            except (OSError, ValueError):
                self.disconnected.set()
                self._stop.set()
                raise

    def set_brightness(self, percent: int) -> None:
        value = round((max(0, min(100, percent)) / 100) ** .75 * 100)
        self._write([command(b'LIG\0\0' + bytes((value,)))])

    def set_small_window(self, mode=1, cpu=0, mem=0, gpu=0) -> None:
        # This model has individual keys; set_buttons draws the wide panel below.
        pass

    def set_buttons(self, buttons: dict[int, Button], partial=False, small_png=None) -> None:
        images = {index: render_icon(button) for index, button in buttons.items() if 0 <= index < 15}
        if small_png:
            with Image.open(io.BytesIO(small_png)) as panel:
                # shortcut: two square keys replace D200's wide LCD, support other models with their own adapter.
                panel = panel.convert('RGB').resize((200, 100), Image.Resampling.LANCZOS)
                for index, left in ((13, 0), (14, 100)):
                    buffer = io.BytesIO()
                    panel.crop((left, 0, left + 100, 100)).save(buffer, 'PNG')
                    images[index] = buffer.getvalue()
        packets = []
        changed = {}
        for index, png in images.items():
            if self._images.get(index) == png:
                continue
            with Image.open(io.BytesIO(png)) as image:
                image = image.convert('RGB').resize((100, 100), Image.Resampling.LANCZOS)
                image = image.transpose(Image.Transpose.ROTATE_90)
                for quality in range(90, 10, -10):
                    buffer = io.BytesIO()
                    image.save(buffer, 'JPEG', quality=quality, subsampling=1)
                    jpeg = buffer.getvalue()
                    if len(jpeg) <= 10240:
                        break
                else:
                    raise ValueError('Mirabox image exceeds 10 KiB')
            packets.append(command(b'BAT' + len(jpeg).to_bytes(4, 'big') + bytes((KEYS[index],))))
            packets.extend(jpeg[offset:offset + PACKET].ljust(PACKET, b'\0')
                           for offset in range(0, len(jpeg), PACKET))
            changed[index] = png
        if packets:
            packets.append(command(b'STP'))
            self._write(packets)
            self._images.update(changed)

    def _parse(self, report: bytes) -> None:
        if len(report) < 11 or report[:3] != b'ACK':
            return
        key, state = report[9:11]
        if key in KEYS and self.on_event:
            self.on_event(InputEvent(KEYS.index(key), 'button', 'press' if state else 'release', state))

    def _keepalive_loop(self) -> None:
        while not self._stop.wait(8):
            try:
                self._write([command(b'CONNECT')])
            except (OSError, ValueError):
                return

    def start(self) -> None:
        self._write([command(b'DIS'), command(b'CONNECT')])
        super().start()

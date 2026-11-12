"""택배(해외 직구) 도착 예상: 알리익스프레스 주문을 운송장 번호로 추적한다.

데이터: ~/.cache/d200/parcels.json  ({"parcels": [{...}]})
  추가:  .venv/bin/python parcels.py add <운송장 번호> "<상품 이름>" [주문일 YYYY-MM-DD]
  목록:  .venv/bin/python parcels.py list
조회:  알리 물류(Cainiao) 공개 조회 주소 (비공식, 로그인 불필요). 30분마다 갱신.
도착 예상: 조회 결과에 예상일이 있으면 그 값, 없으면 지금 단계로 대략 계산.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from clock import _Draw, _kr

try:  # python.org 파이썬은 인증서 묶음이 없어서 certifi 를 쓴다 (market.py 와 같은 방식)
    import ssl

    import certifi

    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _CTX = None

DATA = Path.home() / ".cache" / "d200" / "parcels.json"
POLL_SEC = 30 * 60
SIZE = 196
WIDE = (458, 196)
BG = (22, 24, 34)
TRACK_URL = "https://global.cainiao.com/newDetail.htm?mailNoList={no}"
ALI_TRACK_URL = "https://www.aliexpress.com/p/tracking/index.html?tradeOrderId={id}"
API_URL = "https://global.cainiao.com/global/detail.json?mailNos={nos}&lang=ko-KR"

# 단계: (이름, 색, 남은 날 대략값) — 조회 결과에 예상일이 없을 때 쓰는 값 (알리 → 한국 기준 대략)
STAGES = [
    ("주문", "#7f849c", 9),
    ("발송", "#7aa2f7", 7),
    ("해외 운송", "#bb9af7", 4),
    ("통관", "#e0af68", 2),
    ("국내 배송", "#7dcfff", 1),
    ("배송 출발", "#ff9e64", 0),
    ("도착", "#9ece6a", 0),
]
STAGE = {name: k for k, (name, _, _) in enumerate(STAGES)}
# 이벤트 문구 → 단계 (뒤에 있을수록 우선)
RULES = [
    ("발송", r"left warehouse|preparing to ship|accepted|picked up|received by|shipment|dispatched|handed over to (the )?(line|carrier)|접수|집하|출고"),
    ("해외 운송", r"depart|flight|airline|transit|export|hub|leave|선적|항공|출국|운송 중|간선"),
    ("통관", r"customs|clearance|import|arrived at (the )?destination|통관|세관|입항|도착지 국가"),
    ("국내 배송", r"cj|hanjin|lotte|logen|우체국|post office|handed over to (the )?last.?mile|배송 업체|국내|터미널|간선하차|입고"),
    ("배송 출발", r"out for delivery|배송 ?출발|배달 ?출발|배송중|배달 준비"),
    ("도착", r"delivered|배달 ?완료|배송 ?완료|수령"),
]


@dataclass
class Parcel:
    tracking: str
    title: str = ""
    ordered: str = ""  # YYYY-MM-DD
    stage: int = 0
    events: list[tuple[str, str]] = field(default_factory=list)  # (시각 문자열, 내용) 최신순
    eta: str = ""  # YYYY-MM-DD (조회 결과가 준 예상일, 범위면 첫날)
    eta_end: str = ""  # 예상 범위의 마지막 날
    checked: float = 0.0
    delivered_at: float = 0.0
    order_no: str = ""

    def eta_date(self) -> date | None:
        if self.stage >= STAGE["도착"]:
            return None
        if self.eta:
            try:
                return date.fromisoformat(self.eta)
            except ValueError:
                pass
        base = date.today()
        if self.stage == 0 and self.ordered:
            try:  # 아직 발송 전: 주문일 + 대략 기간 (오늘보다 이르면 오늘부터 다시)
                base = max(base, date.fromisoformat(self.ordered) + timedelta(days=3))
            except ValueError:
                pass
        return base + timedelta(days=STAGES[self.stage][2])

    def days_left(self) -> int | None:
        d = self.eta_date()
        return None if d is None else max(0, (d - date.today()).days)


# ---------- 저장 ----------
_lock = threading.RLock()


def load() -> list[Parcel]:
    try:
        raw = json.loads(DATA.read_text())["parcels"]
    except Exception:
        return []
    out = []
    for p in raw:
        p = dict(p)
        p["events"] = [tuple(e) for e in p.get("events", [])]
        out.append(Parcel(**{k: v for k, v in p.items() if k in Parcel.__dataclass_fields__}))
    return out


def save(parcels: list[Parcel]) -> None:
    with _lock:
        DATA.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA.with_suffix(".tmp")
        tmp.write_text(json.dumps({"parcels": [p.__dict__ for p in parcels]}, ensure_ascii=False, indent=1))
        tmp.replace(DATA)


def add(tracking: str, title: str = "", ordered: str = "", order_no: str = "") -> None:
    tracking = re.sub(r"\s", "", tracking).upper()
    with _lock:
        ps = load()
        for p in ps:
            if p.tracking == tracking or (order_no and p.order_no == order_no):
                p.tracking = tracking or p.tracking
                p.title = title or p.title
                p.ordered = ordered or p.ordered
                p.order_no = order_no or p.order_no
                break
        else:
            ps.append(Parcel(tracking, title, ordered, order_no=order_no))
        save(ps)


# ---------- 조회 ----------
def _stage_of(events: list[tuple[str, str]], status: str = "") -> int:
    best = 0  # 포장 중 같은 기록만 있으면 아직 '주문' 단계
    for _, text in [("", status)] + events:
        low = text.lower()
        for name, pat in RULES:
            if re.search(pat, low):
                best = max(best, STAGE[name])
    return best


def fetch(parcels: list[Parcel]) -> None:
    """Cainiao 조회 (한 번에 여러 개). 실패해도 이전 값 유지."""
    todo = [p for p in parcels if p.tracking and not p.tracking.startswith("ORDER") and p.stage < STAGE["도착"]]
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]
        url = API_URL.format(nos=",".join(p.tracking for p in chunk))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (agentdeck)"})
            data = json.loads(urllib.request.urlopen(req, timeout=20, context=_CTX).read())
        except Exception as e:
            print(f"parcels: lookup failed {e}", flush=True)
            continue
        by_no = {m.get("mailNo"): m for m in data.get("module", [])}
        for p in chunk:
            m = by_no.get(p.tracking)
            if not m:
                continue
            evs = []
            for d in m.get("detailList", []):
                t = d.get("timeStr") or (datetime.fromtimestamp(d["time"] / 1000).strftime("%Y-%m-%d %H:%M")
                                         if d.get("time") else "")
                text = d.get("standerdDesc") or d.get("desc") or ""
                if text:
                    evs.append((t, text.strip()))
            status = " ".join(str(m.get(k) or "") for k in ("statusDesc", "status", "latestTrace"))
            p.events = evs or p.events
            new = _stage_of(p.events, status)
            if new >= STAGE["도착"] and p.stage < STAGE["도착"]:
                p.delivered_at = time.time()
            p.stage = max(p.stage, new)
            eta = _find_eta(m)
            if eta:
                p.eta = eta
            p.checked = time.time()


def _find_eta(m: dict) -> str:
    """조회 결과 어딘가에 들어 있는 예상 도착일 (필드 이름이 바뀌어도 찾게)."""
    for key, val in _walk(m):
        k = key.lower()
        if ("eta" in k or "estimat" in k or "promise" in k) and val:
            if isinstance(val, (int, float)) and val > 1e12:
                return datetime.fromtimestamp(val / 1000).date().isoformat()
            mm = re.search(r"(20\d\d)[-./](\d{1,2})[-./](\d{1,2})", str(val))
            if mm:
                return f"{mm.group(1)}-{int(mm.group(2)):02d}-{int(mm.group(3)):02d}"
    return ""


def _walk(o, key=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(v, k)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, key)
    else:
        yield key, o


def refresh(force: bool = False) -> list[Parcel]:
    with _lock:
        ps = load()
        if force or any(time.time() - p.checked > POLL_SEC for p in ps if p.stage < STAGE["도착"]):
            fetch(ps)
            # 도착하고 이틀 지난 건 목록에서 뺀다
            ps = [p for p in ps if not (p.delivered_at and time.time() - p.delivered_at > 2 * 86400)]
            save(ps)
        return ps


def active(ps: list[Parcel]) -> list[Parcel]:
    """보여줄 순서: 도착한 것(최근) → 빨리 오는 순."""
    def key(p: Parcel):
        dl = p.days_left()
        return (0 if p.stage >= STAGE["도착"] else 1, dl if dl is not None else 99, p.title)
    return sorted(ps, key=key)


def grouped(ps: list[Parcel]) -> list[Parcel]:
    """같은 운송장(한 상자로 묶여 오는 주문)끼리 합쳐 상자 하나로. 제목 = '첫 상품 외 N개'."""
    groups: dict[str, list[Parcel]] = {}
    for p in ps:
        key = p.tracking if p.tracking and not p.tracking.startswith("ORDER") else f"order:{p.order_no or p.tracking}"
        groups.setdefault(key, []).append(p)
    out = []
    for items in groups.values():
        items.sort(key=lambda p: -len(p.events))
        head = items[0]
        if len(items) == 1:
            out.append(head)
            continue
        merged = Parcel(**{**head.__dict__})
        merged.title = f"{head.title[:10]} 외 {len(items) - 1}"
        merged.stage = max(p.stage for p in items)
        merged.eta = min((p.eta for p in items if p.eta), default="")
        merged.eta_end = max((p.eta_end for p in items if p.eta_end), default="")
        merged.count = len(items)  # type: ignore[attr-defined]
        out.append(merged)
    return active(out)


def open_tracking(p: Parcel) -> None:
    url = ALI_TRACK_URL.format(id=p.order_no) if p.order_no else TRACK_URL.format(no=p.tracking)
    import webbrowser
    webbrowser.open(url)


# ---------- 그리기 ----------
def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def when_text(p: Parcel) -> str:
    if p.stage >= STAGE["도착"]:
        return "도착"
    dl = p.days_left()
    return {0: "오늘", 1: "내일"}.get(dl, f"{dl}일 뒤") if dl is not None else "?"


@lru_cache(maxsize=128)
def parcel_tile(title: str, stage: int, when: str, blink: bool, selected: bool) -> bytes:
    """택배 한 칸: 상품 이름 · 도착까지 · 단계 막대."""
    name, color, _ = STAGES[stage]
    col = _rgb(color)
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = _Draw(img)
    hot = stage >= STAGE["배송 출발"] or when in ("오늘", "도착")
    fill = (60, 44, 20) if hot and blink else (32, 35, 50)
    d.rounded_rectangle((6, 6, 189, 189), 22, fill=fill, outline=(250, 210, 60) if selected else col,
                        width=6 if selected else 3)
    short = title if len(title) <= 8 else title[:7] + "…"
    d.text((98, 34), short or "택배", font=_kr(22, 6), fill=(230, 233, 245), anchor="mm")
    d.text((98, 92), when, font=_kr(44 if len(when) <= 3 else 34, 6), fill=col if not hot else (255, 214, 102),
           anchor="mm")
    d.text((98, 136), name, font=_kr(20, 4), fill=col, anchor="mm")
    # 단계 막대 (주문 → 도착)
    n = len(STAGES) - 1
    for k in range(n):
        x0 = 22 + k * (152 / n)
        d.rounded_rectangle((x0 + 2, 158, x0 + 152 / n - 2, 168), 4,
                            fill=col if k < stage or stage == n else (60, 64, 82))
    return _png(img)


@lru_cache(maxsize=16)
def summary_tile(left: int, today: int, week: int) -> bytes:
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = _Draw(img)
    d.rounded_rectangle((6, 6, 189, 189), 22, fill=(40, 30, 20), outline=(255, 120, 60), width=3)
    d.text((98, 30), "11.11 택배", font=_kr(22, 6), fill=(255, 150, 90), anchor="mm")
    d.text((98, 84), str(left), font=_kr(60, 6), fill=(255, 236, 200), anchor="mm")
    d.text((98, 128), "개 오는 중", font=_kr(20, 4), fill=(230, 210, 190), anchor="mm")
    d.text((98, 162), f"오늘 {today} · 7일 내 {week}", font=_kr(18, 4), fill=(200, 190, 180), anchor="mm")
    return _png(img)


def wide_summary(ps: list[Parcel]) -> bytes:
    """넓은 칸: 앞으로 2주 동안 날짜별 도착 예상 막대그래프."""
    img = Image.new("RGB", WIDE, (13, 14, 20))
    d = _Draw(img)
    coming = [p for p in ps if p.stage < STAGE["도착"]]
    days = [0] * 14
    for p in coming:
        dl = p.days_left()
        if dl is not None:
            days[min(dl, 13)] += 1
    d.text((20, 26), f"오는 중 {len(coming)}개", font=_kr(24, 6), fill=(255, 158, 100), anchor="lm")
    last = max((p.eta_date() for p in coming if p.eta_date()), default=None)
    if last:
        d.text((438, 26), f"마지막 예상 {last.month}/{last.day}", font=_kr(18, 4), fill=(170, 176, 200), anchor="rm")
    top = max(days) or 1
    bw = 410 / 14
    for k, n in enumerate(days):
        x = 24 + k * bw
        h = 0 if not n else 18 + 80 * n / top
        if h:
            d.rounded_rectangle((x + 3, 150 - h, x + bw - 3, 150), 4, fill=(255, 158, 100) if k <= 1 else (122, 162, 247))
            d.text((x + bw / 2, 142 - h), str(n), font=_kr(15, 4), fill=(230, 233, 245), anchor="mm")
        if k in (0, 1) or k % 3 == 0:
            day = date.today() + timedelta(days=k)
            lbl = {0: "오늘", 1: "내일"}.get(k, f"{day.month}/{day.day}")
            d.text((x + bw / 2, 172), lbl, font=_kr(14, 4), fill=(150, 156, 180), anchor="mm")
    return _png(img)


def wide_detail(p: Parcel) -> bytes:
    """넓은 칸: 고른 택배의 최근 이동 기록."""
    img = Image.new("RGB", WIDE, (13, 14, 20))
    d = _Draw(img)
    name, color, _ = STAGES[p.stage]
    d.text((20, 24), (p.title or p.tracking)[:18], font=_kr(22, 6), fill=_rgb(color), anchor="lm")
    eta = p.eta_date()
    d.text((438, 24), "도착" if p.stage >= STAGE["도착"] else (f"{eta.month}/{eta.day} 예상" if eta else ""),
           font=_kr(18, 4), fill=(255, 214, 102), anchor="rm")
    evs = p.events[:4] or [("", "아직 이동 기록이 없어요 (발송 전)")]
    for k, (t, text) in enumerate(evs):
        y = 60 + k * 32
        d.ellipse((22, y - 5, 32, y + 5), fill=_rgb(color) if k == 0 else (90, 94, 110))
        line = text if len(text) <= 26 else text[:25] + "…"
        d.text((42, y), line, font=_kr(17, 4 if k else 6), fill=(230, 233, 245) if k == 0 else (160, 166, 190),
               anchor="lm")
        if t:
            d.text((438, y), t[5:16] if len(t) >= 16 else t, font=_kr(13, 2), fill=(130, 136, 160), anchor="rm")
    d.text((20, 186), f"{p.tracking} · 길게: 브라우저로 조회", font=_kr(13, 2), fill=(110, 116, 140), anchor="lm")
    return _png(img)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "add":
        add(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "", sys.argv[4] if len(sys.argv) > 4 else "")
    for p in active(refresh(force=True)):
        print(f"{p.tracking:22} {STAGES[p.stage][0]:6} {when_text(p):6} {p.title}  {p.events[:1]}")

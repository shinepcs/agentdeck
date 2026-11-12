"""한국 주식 히트맵 데이터 (HeatTab 과 같은 네이버 증권 데이터, 비공식 API).

보기 6가지 (대시보드 가운데 버튼으로 전환)
  top       : KOSPI 시가총액 상위 10종목
  kosdaq    : KOSDAQ 시가총액 상위 10종목
  movers    : 업종 등락 상위 5 + 하위 5
  portfolio : config.json market.portfolio 종목코드 목록
  sectors   : config.json market.sectors 관심 업종 (고정 위치)
  macro     : 환율·원자재·금리 (USD/KRW, JPY/KRW, EUR/KRW, 달러인덱스, WTI, 브렌트, 금, 은, 미 10년·2년물)
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.request
from dataclasses import dataclass

try:
    import certifi

    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # certifi 없으면 시스템 기본
    _CTX = ssl.create_default_context()

from config import CFG

MARKET_CFG: dict = CFG.get("market") or {}
MARKET_ENABLED: bool = bool(MARKET_CFG.get("enabled"))
PORTFOLIO: list[str] = MARKET_CFG.get("portfolio", [])
FAV_SECTORS: list[str] = MARKET_CFG.get("sectors", [
    "반도체와반도체장비", "전기제품", "자동차", "조선", "우주항공과국방",
    "생물공학", "제약", "은행", "증권", "소프트웨어"])
VIEWS = ["top", "kosdaq", "movers", "portfolio", "sectors", "macro"]
VIEW_LABEL = {"top": "코스피 상위", "kosdaq": "코스닥 상위", "movers": "업종 등락", "portfolio": "내 포트폴리오",
              "sectors": "관심 업종", "macro": "환율·원자재·금리"}

# 지표: (표시 이름, 네이버 분류, 코드, 형식)  형식 rate = 금리(%, 등락은 bp)
MACRO: list[tuple[str, str, str, str]] = [
    ("USD/KRW", "exchange", "FX_USDKRW", "fx"), ("100JPY/KRW", "exchange", "FX_JPYKRW", "fx"),
    ("EUR/KRW", "exchange", "FX_EURKRW", "fx"), ("DXY", "exchange", ".DXY", "num"),
    ("WTI", "energy", "CLcv1", "usd"), ("Brent", "energy", "LCOcv1", "usd"),
    ("Gold", "metals", "GCcv1", "usd"), ("Silver", "metals", "SIcv1", "usd"),
    ("US 10Y", "bond", "US10YT=RR", "rate"), ("US 2Y", "bond", "US2YT=RR", "rate"),
]


@dataclass
class Quote:
    name: str
    change: float | None  # 등락률 %
    price: str = ""  # 표시용 현재가 (업종은 상승/하락 종목 수)
    code: str = ""
    value: str | None = None  # 지표: 큰 글씨로 보일 값 (있으면 등락률 대신 이 값을 크게)
    note: str | None = None  # 지표: 아래 줄 (등락률·bp)


@dataclass
class Index:
    name: str
    price: str
    change: float | None
    status: str  # OPEN / CLOSE


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10, context=_CTX) as r:
        return json.loads(r.read())


def _ratio(row: dict, key: str = "fluctuationsRatio") -> float | None:
    """네이버 등락률. 하락(코드 4·5)인데 양수로 오면 음수로 고친다 (HeatTab 과 같은 처리)."""
    try:
        v = float(str(row.get(key)).replace(",", ""))
    except (TypeError, ValueError):
        return None
    code = str((row.get("compareToPreviousPrice") or row.get("fluctuationsType") or {}).get("code", ""))
    return -v if code in ("4", "5") and v > 0 else v


def indices() -> list[Index]:
    out = []
    for name in ("KOSPI", "KOSDAQ"):
        try:
            d = _get(f"https://m.stock.naver.com/api/index/{name}/basic")
            out.append(Index(name, d.get("closePrice", "-"), _ratio(d), d.get("marketStatus", "")))
        except Exception:
            out.append(Index(name, "-", None, ""))
    return out


def top_mcap(n: int = 10, market: str = "KOSPI") -> list[Quote]:
    d = _get(f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page=1&pageSize={n + 6}")
    rows = [r for r in d.get("stocks", []) if r.get("stockEndType") == "stock"]
    return [Quote(r["stockName"], _ratio(r), r.get("closePrice", ""), r.get("itemCode", "")) for r in rows[:n]]


def _num(s) -> float | None:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def macro() -> list[Quote]:
    """환율·원자재·금리 10개 (동시에 조회)."""
    from concurrent.futures import ThreadPoolExecutor

    def one(item):
        label, cat, code, fmt = item
        try:
            d = _get(f"https://m.stock.naver.com/front-api/marketIndex/productDetail?category={cat}&reutersCode={code}")["result"]
        except Exception:
            return Quote(label, None, "", code, "-", "조회 실패")
        ratio, price = _ratio(d), _num(d.get("closePrice"))
        if price is None:
            return Quote(label, ratio, "", code, "-", "")
        if fmt == "rate":  # 금리: 값은 %, 변동은 bp
            diff = _num(d.get("fluctuations")) or 0
            if ratio is not None and ratio < 0 and diff > 0:
                diff = -diff
            return Quote(label, ratio, "", code, f"{price:.3f}%", f"{diff * 100:+.1f}bp")
        value = f"{price:,.1f}" if fmt == "fx" else (f"${price:,.2f}" if fmt == "usd" else f"{price:,.2f}")
        return Quote(label, ratio, "", code, value, "-" if ratio is None else f"{ratio:+.2f}%")

    with ThreadPoolExecutor(5) as pool:
        return list(pool.map(one, MACRO))


def _sectors() -> list[Quote]:
    d = _get("https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=100")
    out = []
    for g in d.get("groups", []):
        out.append(Quote(g["name"], _ratio(g, "changeRate"), f"▲{g.get('riseCount', 0)} ▼{g.get('fallCount', 0)}",
                         str(g.get("no", ""))))
    return out


def movers() -> list[Quote]:
    qs = sorted((q for q in _sectors() if q.change is not None), key=lambda q: q.change, reverse=True)
    return qs[:5] + qs[-5:] if len(qs) >= 10 else qs


def fav_sectors() -> list[Quote]:
    by_name = {q.name: q for q in _sectors()}
    return [by_name.get(n, Quote(n, None, "없는 업종")) for n in FAV_SECTORS[:10]]


def portfolio() -> list[Quote]:
    out = []
    for code in PORTFOLIO[:10]:
        try:
            d = _get(f"https://m.stock.naver.com/api/stock/{code}/basic")
            out.append(Quote(d.get("stockName", code), _ratio(d), d.get("closePrice", ""), code))
        except Exception:
            out.append(Quote(code, None, "조회 실패", code))
    return out


def breadth() -> tuple[int, int]:
    """전체 업종 기준 상승·하락 종목 수 합계."""
    try:
        d = _get("https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=100")
        gs = d.get("groups", [])
        return sum(int(g.get("riseCount") or 0) for g in gs), sum(int(g.get("fallCount") or 0) for g in gs)
    except Exception:
        return 0, 0


_cache: dict[str, tuple[float, object]] = {}


def view_data(view: str, ttl: float = 60) -> list[Quote] | None:
    """보기별 데이터 (ttl 초 캐시). 실패하면 None."""
    hit = _cache.get(view)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]  # type: ignore[return-value]
    fn = {"top": top_mcap, "kosdaq": lambda: top_mcap(market="KOSDAQ"), "movers": movers, "portfolio": portfolio,
          "sectors": fav_sectors, "macro": macro}[view]
    try:
        data = fn()
    except Exception:
        return hit[1] if hit else None  # type: ignore[return-value]
    _cache[view] = (time.time(), data)
    return data


def open_heattab() -> None:
    """크롬에 새 탭을 연다 (HeatTab 확장이 새 탭을 대체하므로 히트맵이 뜬다)."""
    import os
    if os.name == 'nt':
        import webbrowser
        webbrowser.open('https://heattab.app')
        return
    import subprocess

    subprocess.run(["osascript", "-e", '''tell application "Google Chrome"
  activate
  if (count of windows) = 0 then make new window
  tell front window to make new tab at end of tabs
end tell'''], capture_output=True, timeout=10)


if __name__ == "__main__":
    print(indices(), breadth())
    for v in VIEWS:
        print(v, [(q.name, q.change) for q in (view_data(v) or [])])

"""대시보드 페이지 구성.

공통 하단 줄: [◀ 이전][페이지 n/N][다음 ▶] + 오른쪽 넓은 칸 시계
  - 버튼 10/12 로 페이지 넘김, 11 은 즉시 갱신(길게 누르면 밝기 등 추후 확장)

페이지 1 · 요약      : LLM 당 한 칸(남은 % + 5H/주간 미니 게이지), 페이스, 추천, 스튜디오 요약
페이지 2 · 한도 그리드 : 열=LLM, 1줄=5H, 2줄=주간 (2줄 구성)
페이지 3 · 스튜디오    : Herdr 스튜디오 프로젝트/에이전트 현황
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from d200 import Button
from machines import MachineStat, Volume, external_drives
from remote_herdr import TOWER_SPACE, Member, StudioState, TowerMeta, Workspace, child_kinds, tower_split
from usage import until

BG = "#16161e"
NAV_BG = "#24283b"
DIM = "#565f89"
GREEN, YELLOW, RED = "#9ece6a", "#e0af68", "#f7768e"


@dataclass
class Limit:
    """한 LLM 의 한도 창 하나 (남은 비율 기준)."""

    remaining: float | None  # 0~1, None = 정보 없음
    reset: datetime | None
    window: timedelta


@dataclass
class LLM:
    name: str
    color: str
    five: Limit | None = None
    week: Limit | None = None
    extra: str = ""  # 예: 크레딧
    login: bool = False  # 로그인이 풀려 한도를 못 읽는 상태 (칸을 길게 누르면 로그인 창)

    def binding(self) -> Limit | None:
        """더 빡빡한(남은 게 적은) 창."""
        cands = [x for x in (self.five, self.week) if x and x.remaining is not None]
        return min(cands, key=lambda x: x.remaining) if cands else None


def color_for(remaining: float | None) -> str:
    if remaining is None:
        return DIM
    if remaining > 0.4:
        return GREEN
    if remaining > 0.15:
        return YELLOW
    return RED


def pace(lim: Limit | None, now: datetime) -> float | None:
    """사용률 - 경과율 (양수 = 시간 대비 빨리 쓰는 중). 퍼센트 포인트."""
    if not lim or lim.remaining is None or not lim.reset:
        return None
    left = (lim.reset - now).total_seconds() / lim.window.total_seconds()
    elapsed = min(1.0, max(0.0, 1 - left))
    return (1 - lim.remaining - elapsed) * 100


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


# ---------- 공통 ----------
def nav(page: int, total: int, brightness: int, middle: tuple[str, str] | None = None) -> dict[int, Button]:
    """middle: (제목, 아래 줄) 로 가운데 버튼 문구를 바꿀 수 있다 (예: 히트맵 보기 전환)."""
    if middle:
        return {
            10: Button(header="이전", title="◀", sub="", bg=NAV_BG, accent=DIM),
            11: Button(header=f"{page}/{total} 페이지", title=middle[0], sub=middle[1], bg=NAV_BG, accent=DIM),
            12: Button(header="다음", title="▶", sub="", bg=NAV_BG, accent=DIM),
        }
    return {
        10: Button(header="이전", title="◀", sub="", bg=NAV_BG, accent=DIM),
        11: Button(header=f"{page}/{total} 페이지", title="홈", sub=f"길게: 밝기 {brightness}", bg=NAV_BG, accent=DIM),
        12: Button(header="다음", title="▶", sub="", bg=NAV_BG, accent=DIM),
    }


# ---------- 페이지 1: 요약 ----------
def login_tile(header: str) -> Button:
    return Button(header=header, title="로그인", sub="길게: 로그인", bg=BG, accent=YELLOW, border=YELLOW)


def llm_tile(m: LLM) -> Button:
    if m.login:
        return login_tile(m.name)
    b = m.binding()
    return Button(
        header=m.name,
        title=pct(b.remaining if b else None),
        bg=BG,
        accent=m.color,
        bars=[
            ("5H", m.five.remaining if m.five else None, color_for(m.five.remaining if m.five else None)),
            ("주간", m.week.remaining if m.week else None, color_for(m.week.remaining if m.week else None)),
        ],
        border=RED if b and b.remaining is not None and b.remaining < 0.15 else None,
        sub=f"리셋 {until(b.reset)}" if b else "",
    )


def page_summary(llms: list[LLM], studio: StudioState, now: datetime, blink_on: bool = False) -> dict[int, Button]:
    p: dict[int, Button] = {i: Button(bg=BG) for i in (0, 1, 2, 5, 6, 7)}  # 안 쓰는 LLM 자리는 빈 칸
    for i, m in enumerate(llms[:3]):
        p[i] = llm_tile(m)
    # 추천: 가장 여유 있는 LLM
    ranked = sorted((m for m in llms if m.binding()), key=lambda m: m.binding().remaining, reverse=True)
    if ranked:
        best = ranked[0]
        p[3] = Button(header="지금 쓰기 좋은", title=best.name.split()[0], sub=f"여유 {pct(best.binding().remaining)}",
                      bg=BG, accent=best.color)
    else:
        p[3] = Button(bg=BG)
    # 다음 리셋
    # 다 남아 있는 창(=아직 안 씀)은 리셋 의미가 없으니 제외
    resets = [(m.name, l.reset) for m in llms for l in (m.five, m.week)
              if l and l.reset and l.reset > now and (l.remaining or 0) < 0.999]
    if resets:
        name, r = min(resets, key=lambda x: x[1])
        p[4] = Button(header="다음 리셋", title=until(r, now), sub=name, bg=BG, accent=DIM)
    else:
        p[4] = Button(bg=BG)
    # 2줄: 주간 페이스 3칸 + 스튜디오 2칸
    for i, m in enumerate(llms[:3]):
        pc = pace(m.week, now)
        if pc is None:
            p[5 + i] = Button(header=f"{m.name.split()[0]} 페이스", title="-", sub="정보 없음", bg=BG, accent=m.color)
        else:
            tag = "과속" if pc > 10 else ("여유" if pc < -10 else "적정")
            col = RED if pc > 10 else (GREEN if pc < -10 else YELLOW)
            p[5 + i] = Button(header=f"{m.name.split()[0]} 페이스", title=tag, sub=f"{pc:+.0f}%p", bg=BG, accent=col)
    if studio.attention or studio.done:  # 결정 필요(노랑) / 완료 알림(초록): 깜빡임, 누르면 해당 창으로
        title, color = (f"결정 {studio.attention}", YELLOW) if studio.attention else (f"완료 {studio.done}", GREEN)
        p[8] = Button(header="스튜디오", title=title, sub="눌러서 이동",
                      bg=color if blink_on else BG, fg="#16161e" if blink_on else "#ffffff",
                      accent="#16161e" if blink_on else color, border=None if blink_on else color)
    else:
        p[8] = Button(header="스튜디오", title="ON" if studio.online else "OFF",
                      sub=f"작업 {studio.working}", bg=BG, accent=GREEN if studio.online else RED)
    p[9] = Button(header="갱신", title=now.astimezone().strftime("%H:%M"), sub="30초마다", bg=BG, accent=DIM)
    return p


# ---------- 페이지 2: 한도 그리드 (열 = LLM, 1줄 5H, 2줄 주간) ----------
def credit_tiles(name: str, color: str, d: dict, now: datetime) -> tuple[Button, Button]:
    """웹 크레딧 서비스(Flow, Higgsfield): 위 칸 = 남은 크레딧, 아래 칸 = 요금제와 마지막 확인 시각."""
    reset = datetime.fromisoformat(d["reset"]) if d.get("reset") else None
    credits, total = d.get("credits"), d.get("total")
    if reset:
        sub = f"리셋 {until(reset, now)}"
    elif total:
        sub = f"/ {total:,}"
    else:
        sub = "리셋 정보 없음"
    top = Button(header=f"{name} 크레딧", title="-" if credits is None else f"{credits:,}", sub=sub, bg=BG,
                 accent=color, ratio=(credits / total) if credits is not None and total else None)
    checked = datetime.fromisoformat(d["checked"]) if d.get("checked") else None
    stale = checked is None or (now - checked).total_seconds() > 3 * 3600
    bottom = Button(header=f"{name} 요금제", title=d.get("tier") or "-",
                    sub=("갱신 " + checked.strftime("%H:%M")) if checked else "확인 전",
                    bg=BG, accent=DIM if stale else color)
    return top, bottom


def page_grid(llms: list[LLM], now: datetime, credits: list[tuple[str, str, dict]] | None = None) -> dict[int, Button]:
    """LLM 한 개당 한 열(5H/주간), 그 뒤에 웹 크레딧 서비스 한 개당 한 열."""
    p: dict[int, Button] = {}
    for k, (name, color, d) in enumerate(credits or []):
        col = len(llms) + k
        if col < 5:
            p[col], p[5 + col] = credit_tiles(name, color, d, now)
    for col in range(5):
        if col in p:
            continue
        m = llms[col] if col < len(llms) else None
        for row, attr, label in ((0, "five", "5H"), (1, "week", "주간")):
            idx = row * 5 + col
            if m is None:
                p[idx] = Button(bg=BG)
                continue
            lim: Limit | None = getattr(m, attr)
            if m.login:
                p[idx] = login_tile(f"{m.name.split()[0]} {label}")
            elif lim is None or lim.remaining is None:
                p[idx] = Button(header=f"{m.name.split()[0]} {label}", title="-", sub="없음", bg=BG, accent=m.color)
            else:
                p[idx] = Button(header=f"{m.name.split()[0]} {label}", title=pct(lim.remaining),
                                sub=f"리셋 {until(lim.reset, now)}", bg=BG, accent=m.color,
                                ratio=lim.remaining)
                p[idx].accent = m.color
    return p


# ---------- 페이지 3: 스튜디오 ----------
# 색 테마: 총괄 = 보라, 스튜디오 = 파랑 (알림 노랑/초록은 공통)
STUDIO_THEME = {"bg": BG, "accent": "#7aa2f7", "idle": DIM}
TOWER_THEME = {"bg": "#2a2142", "accent": "#bb9af7", "idle": "#a493d6"}


def _alert_tile(header: str, title: str, sub: str, color: str, blink_on: bool, theme: dict = STUDIO_THEME,
                raw: bool = False) -> Button:
    if blink_on:
        return Button(header=header, raw_header=raw, title=title, sub=sub, bg=color, fg="#16161e", accent="#16161e")
    return Button(header=header, raw_header=raw, title=title, sub=sub, bg=theme["bg"], accent=color, border=color)


def studio_tile(w: Workspace, blink_on: bool, header: str | None = None, theme: dict = STUDIO_THEME) -> Button:
    """스튜디오 한 칸: 알림(결정/완료) 깜빡임 + 실행 중 에이전트 수."""
    raw = header is None  # 스튜디오 이름(사용자 데이터)은 번역하지 않음
    header = header or w.name.replace(" · 스튜디오", "")
    # 아래 줄: 에이전트 종류별 개수(C=Claude, X=Codex, A=agy) + 지금 실행 중인 수
    mix = " ".join(f"{k}{v}" for k, v in sorted(w.agents.items()))
    running = f"{mix} · 실행 {w.working}" if mix else f"실행 {w.working}"
    if w.attention:
        return _alert_tile(header, f"결정 {w.attention}", running, YELLOW, blink_on, theme, raw)
    if w.done:
        return _alert_tile(header, f"완료 {w.done}", running, GREEN, blink_on, theme, raw)
    if w.working:
        return Button(header=header, raw_header=raw, title=f"작업 {w.working}", sub=running, bg=theme["bg"], accent=theme["accent"],
                      border=theme["accent"])
    return Button(header=header, raw_header=raw, title="대기", sub=running, bg=theme["bg"], accent=theme["idle"])


APP_LABEL = {"claude-code": "Claude", "codex": "Codex", "antigravity": "AGY"}


def children_text(kinds: list[tuple[str, str | None]], app: str) -> str:
    """하위 에이전트 요약: '하위 X2 · 실행 2' / 없으면 pane 자신의 종류."""
    if not kinds:
        return app
    counts: dict[str, int] = {}
    for k, _ in kinds:
        counts[k] = counts.get(k, 0) + 1
    mix = " ".join(f"{k}{v}" for k, v in sorted(counts.items(), key=lambda x: x[0] == "기타"))
    running = sum(1 for _, st in kinds if st == "working")
    return f"하위 {mix}" + (f" · 실행 {running}" if running else "")


def pane_tile(tower: Workspace, m: Member, name: str, kinds: list, blink_on: bool) -> Button:
    th = TOWER_THEME
    header = (name or "총괄").replace(" 총괄", "") or "총괄"
    sub = children_text(kinds, APP_LABEL.get(m.app or "", ""))
    st = tower.state_of(m.term)
    if st == "attention":
        return _alert_tile(header, "결정", sub, YELLOW, blink_on, th, True)
    if st == "done":
        return _alert_tile(header, "완료", sub, GREEN, blink_on, th, True)
    if st == "working":
        return Button(header=header, raw_header=True, title="작업 중", sub=sub, bg=th["bg"], accent=th["accent"], border=th["accent"])
    if any(k_st == "working" for _, k_st in kinds):  # 총괄은 쉬는데 하위가 일하는 중
        return Button(header=header, raw_header=True, title="위임 중", sub=sub, bg=th["bg"], accent=th["accent"], border="#7a5fc0")
    return Button(header=header, raw_header=True, title="대기", sub=sub, bg=th["bg"], accent=th["idle"])


def page_studio(studio: StudioState, blink_on: bool, row: list[Workspace], meta: TowerMeta | None = None) -> dict[int, Button]:
    """작업 현황.

    윗줄  : 총괄 스튜디오(보라) — 리드 탭 pane 4칸(이름 + 하위 에이전트) + 나머지 탭을 묶은 '기타 총괄' 1칸
    가운데: 스튜디오 5칸 (row 순서, 대시보드가 알림 우선으로 정해 넘긴다)
    결정 필요(노랑)·완료 알림(초록)은 blink_on 일 때 반전되어 깜빡인다.
    """
    p: dict[int, Button] = {i: Button(bg=BG) for i in range(10)}
    if not studio.online:
        p[0] = Button(header="스튜디오", title="OFF", sub="연결 안 됨·미설정", bg=BG, accent=RED)
        return p
    tower = next((w for w in studio.workspaces if w.name == TOWER_SPACE), None)
    if tower:
        panes, rest = tower_split(tower)
        meta = meta or TowerMeta({}, {})
        for i, m in enumerate(panes[:4]):
            p[i] = pane_tile(tower, m, meta.names.get(m.term, f"총괄 {i + 1}"), child_kinds(meta, m), blink_on)
        p[4] = studio_tile(rest, blink_on, header="기타 총괄", theme=TOWER_THEME)
    if tower:
        for i, w in enumerate(row[:5]):
            p[5 + i] = studio_tile(w, blink_on)
    else:  # 리드 스페이스가 없으면(훅 방식 등) 10칸 모두 프로젝트
        for i, w in enumerate(row[:10]):
            p[i] = studio_tile(w, blink_on)
    return p

# ---------- 페이지 4: 머신 (열 = 컴퓨터, 윗줄 자원 게이지, 아랫줄 디스크 남은 용량) ----------
def used_color(pct: float, warn: float = 70, crit: float = 85) -> str:
    return RED if pct >= crit else (YELLOW if pct >= warn else GREEN)


def fmt_gb(gb: float) -> str:
    if gb >= 1024:
        return f"{gb / 1024:.1f}TB"
    return f"{gb:.0f}GB" if gb >= 10 else f"{gb:.1f}GB"


def drive_tile(v: Volume) -> Button:
    if not v.mounted:
        return Button(header=v.name, title="분리됨", sub=v.machine, bg=BG, accent=RED, border=RED)
    return Button(header=v.name, title=fmt_gb(v.free_gb), sub=f"{v.machine} · {fmt_gb(v.total_gb)}",
                  bg=BG, accent=used_color(v.used_pct, 80, 90), ratio=1 - v.used_pct / 100,
                  border=RED if v.used_pct >= 90 else None)


def page_machines(stats: list[MachineStat], now: datetime, mole: dict | None = None,
                  dry: dict | None = None) -> dict[int, Button]:
    """mole: 이름 → MoleStatus, dry: 이름 → dry-run 정보. 칸을 누르면 기기 상세 페이지."""
    mole, dry = mole or {}, dry or {}
    p: dict[int, Button] = {i: Button(bg=BG) for i in range(10)}
    for col, m in enumerate(stats[:4]):
        if not m.online:
            p[col] = Button(header=m.name, title="OFF", sub="연결 안 됨", bg=BG, accent=RED, border=RED)
            p[col + 5] = Button(header=m.name, title="-", sub="", bg=BG, accent=DIM)
            continue
        worst = max(m.cpu / 90 * 85, m.mem_used, m.disk_used)  # CPU 는 순간값이라 조금 느슨하게
        p[col] = Button(
            header=m.name, bg=BG, accent="#c0caf5",
            bars=[
                ("CPU", m.cpu / 100, used_color(m.cpu, 70, 90), f"{m.cpu:.0f}%"),
                ("메모리", m.mem_used / 100, used_color(m.mem_used, 75, 90), f"{m.mem_used:.0f}%"),
                ("디스크", m.disk_used / 100, used_color(m.disk_used, 80, 90), f"{m.disk_used:.0f}%"),
            ],
            sub=(f"건강 {mole[m.name].health} · 가동 {m.uptime_days:.0f}일" if m.name in mole
                 else f"{m.mem_gb:.0f}GB · 가동 {m.uptime_days:.0f}일"),
            border=RED if worst >= 90 else (YELLOW if m.name in mole and mole[m.name].health < 70 else None),
        )
        free = m.disk_free_gb
        p[col + 5] = Button(
            header=f"{m.name} 디스크", title=fmt_gb(free),
            sub=(f"정리 가능 {fmt_gb(dry[m.name]['clean_gb'])}" if dry.get(m.name, {}).get("clean_gb") else "남은 용량"),
            bg=BG, accent=used_color(m.disk_used, 80, 90),
            ratio=1 - m.disk_used / 100, border=RED if m.disk_used >= 90 else None,
        )
    # 오른쪽 열: 외장 드라이브 (머신·갱신 칸 대신)
    for slot, v in zip((4, 9), external_drives(stats)):
        p[slot] = drive_tile(v)
    return p


# ---------- 페이지 5: 뽀모도로 ----------
POMO_RED, POMO_PAUSE = "#f7768e", "#e0af68"


def page_pomodoro(pomo, blink_on: bool) -> dict[int, Button]:
    """setup: 프리셋 10칸 / running·paused: 10칸이 마지막 칸부터 거꾸로 비워짐 / done: 전체 깜빡임."""
    from pomodoro import PRESETS

    p: dict[int, Button] = {}
    if pomo.state == "setup":
        for i, mins in enumerate(PRESETS):
            p[i] = Button(header="뽀모도로" if mins == 25 else "", title=f"{mins}분", sub="누르면 시작",
                          bg="#2a1a22" if mins == 25 else BG, accent=POMO_RED, border=POMO_RED if mins == 25 else None)
        return p
    if pomo.state == "done":
        for i in range(10):
            on = blink_on ^ (i % 2 == 0)  # 체크무늬로 번갈아 깜빡임
            p[i] = Button(title="완료" if i in (4, 5) else "", sub="눌러서 닫기" if i == 5 else "",
                          bg=POMO_RED if on else BG, fg="#16161e" if on else "#ffffff")
        return p
    color = POMO_RED if pomo.state == "running" else POMO_PAUSE
    cells = pomo.fraction() * 10  # 남은 칸 수 (소수)
    for i in range(10):
        f = max(0.0, min(1.0, cells - i))  # 앞칸부터 채워지고, 마지막 칸부터 비워진다
        p[i] = Button(bg="#16161e", fill=f, fill_color=color, fg="#16161e" if f > 0.55 else "#c0caf5")
    # 현재 줄어드는 칸에 남은 분 표시
    cur = min(9, int(cells)) if cells > 0 else 0
    p[cur].title = f"{int(pomo.remaining() // 60) + 1}분" if pomo.state == "running" else "Ⅱ"
    if pomo.state == "paused":  # 일시정지 중: 마지막 칸 = 취소, 나머지 = 계속
        p[9] = Button(header="타이머", title="취소", sub="눌러서 종료", bg="#3a1d24", accent=POMO_RED, border=POMO_RED)
    return p


# ---------- 워크트리 페이지 (작업 현황에서 들어가는 하위 페이지) ----------
def short_name(name: str, limit: int = 16) -> str:
    """칸에 맞게 줄이기: 끝의 날짜(-20261103), 긴 해시(12자 이상 16진수) 제거 후 길면 자르기."""
    import re

    n = re.sub(r"-20\d{6}$", "", name)
    n = re.sub(r"[0-9a-f]{12,}", lambda m: m.group(0)[:6], n)
    return n if len(n) <= limit else n[: limit - 1] + "…"


def page_worktrees(items, armed_path: str | None, armed_action: str | None) -> dict[int, Button]:
    from clock import WT_COLORS

    p: dict[int, Button] = {i: Button(bg=BG) for i in range(10)}
    if items is None:
        p[0] = Button(header="워크트리", title="-", sub="스튜디오 연결 안 됨", bg=BG, accent=RED)
    for i, w in enumerate((items or [])[:10]):
        color = WT_COLORS.get(w.state, DIM)
        info = f"변경 {w.dirty}" if w.dirty else f"앞섬 {w.ahead if w.ahead is not None else '?'}"
        # 맨 위: 프로젝트(저장소) 이름을 밝게 / 가운데: 상태 / 아래: 워크트리 이름 + 변경·앞선 커밋 수
        sub = f"{short_name(w.name, 14)} · {info}"
        if w.path == armed_path:  # 길게 한 번 누름: 확인 대기 (빨강)
            title = "삭제?" if armed_action == "remove" else "총괄 지시?"
            p[i] = Button(header=short_name(w.repo), raw_header=True, header_fg="#16161e", title=title, sub="길게 한 번 더", bg=RED, fg="#16161e")
            continue
        p[i] = Button(header=short_name(w.repo), raw_header=True, header_fg="#e6e9f5", title=w.state, sub=sub, bg="#1f2233", accent=color,
                      border=color)
    return p


def nav_worktrees(brightness: int) -> dict[int, Button]:
    return {
        10: Button(header="뒤로", title="◀", sub="작업 현황", bg=NAV_BG, accent=DIM),
        11: Button(header="워크트리", title="갱신", sub=f"길게: 밝기 {brightness}", bg=NAV_BG, accent=DIM),
        12: Button(header="다음", title="▶", sub="머신", bg=NAV_BG, accent=DIM),
    }


# ---------- 기기 상세 페이지 (머신 페이지에서 컴퓨터를 눌러 들어감) ----------
def health_color(score: int) -> str:
    return GREEN if score >= 80 else (YELLOW if score >= 60 else RED)


def page_device(m: MachineStat, ms, dry: dict, trash, armed: str | None) -> dict[int, Button]:
    """윗줄: 건강·CPU·메모리·디스크·휴지통 / 아랫줄: CPU 상위 2 + [캐시 정리] [산출물 정리] [휴지통 비우기]."""
    p: dict[int, Button] = {i: Button(bg=BG) for i in range(10)}
    if not m.online:
        p[0] = Button(header=m.name, title="OFF", sub="연결 안 됨", bg=BG, accent=RED, border=RED)
        return p
    if ms:
        p[0] = Button(header=f"{m.name} 건강", title=str(ms.health), sub=ms.health_msg.replace("Restart Recommended", "재시작 권장"),
                      bg=BG, accent=health_color(ms.health), border=health_color(ms.health), ratio=ms.health / 100)
    else:
        p[0] = Button(header=m.name, title="-", sub="Mole 없음", bg=BG, accent=DIM)
    p[1] = Button(header="CPU", title=f"{m.cpu:.0f}%", sub="사용률", bg=BG, accent=used_color(m.cpu, 70, 90), ratio=m.cpu / 100)
    p[2] = Button(header="메모리", title=f"{m.mem_used:.0f}%", sub=f"{m.mem_gb:.0f}GB 중", bg=BG,
                  accent=used_color(m.mem_used, 75, 90), ratio=m.mem_used / 100)
    clean = dry.get("clean_gb")
    p[3] = Button(header="디스크 남음", title=fmt_gb(m.disk_free_gb),
                  sub=f"캐시 정리 가능 {fmt_gb(clean)}" if clean else f"{m.disk_used:.0f}% 사용", bg=BG,
                  accent=used_color(m.disk_used, 80, 90), ratio=1 - m.disk_used / 100)
    if trash:
        p[4] = Button(header="휴지통", title=fmt_gb(trash[1]) if trash[1] >= 0.05 else "비어 있음",
                      sub=f"{trash[0]}개 항목" if trash[0] >= 0 else "Mole 측정값",
                      bg=BG, accent=YELLOW if trash[1] >= 1 else DIM)
    if not ms:
        return p
    for i, (name, cpu) in enumerate(ms.top[:2]):
        alert = any(a.startswith(name) for a in ms.alerts)
        p[5 + i] = Button(header=f"CPU {i + 1}위", title=name, sub=f"{cpu:.0f}%", bg=BG,
                          accent=RED if alert else "#7aa2f7", border=RED if alert else None)
    # 실행 버튼 (길게 두 번)
    if armed == "clean":
        p[7] = Button(header="캐시·로그", title="정리?", sub="길게 한 번 더", bg=RED, fg="#16161e", header_fg="#16161e")
    else:
        if clean is not None:
            csub = fmt_gb(clean)
        else:
            csub = "측정 중…" if dry.get("measuring") else "길게 2번: 정리"
        p[7] = Button(header="캐시·로그", title="정리", sub=csub, bg="#1f2233", accent="#ff9e64", border="#ff9e64")
    if armed == "purge":
        p[8] = Button(header="빌드 산출물", title="정리?", sub="길게 한 번 더", bg=RED, fg="#16161e", header_fg="#16161e")
    else:
        if dry.get("purge_gb") is not None:
            sub = f"{fmt_gb(dry['purge_gb'])} · {dry.get('purge_items', 0)}개"
        else:
            sub = "측정 중…" if dry.get("measuring") else "길게 2번: 정리"
        p[8] = Button(header="빌드 산출물", title="정리", sub=sub, bg="#1f2233", accent="#ff9e64", border="#ff9e64")
    if armed == "trash":
        p[9] = Button(header="휴지통", title="비우기?", sub="길게 한 번 더", bg=RED, fg="#16161e", header_fg="#16161e")
    else:
        tsub = (f"{fmt_gb(trash[1])} · {trash[0]}개" if trash[0] >= 0 else fmt_gb(trash[1])) if trash else "길게 2번: 비우기"
        p[9] = Button(header="휴지통", title="비우기", sub=tsub, bg="#1f2233", accent="#ff9e64", border="#ff9e64")
    return p


def nav_device(brightness: int) -> dict[int, Button]:
    return {
        10: Button(header="뒤로", title="◀", sub="머신", bg=NAV_BG, accent=DIM),
        11: Button(header="기기", title="갱신", sub=f"길게: 밝기 {brightness}", bg=NAV_BG, accent=DIM),
        12: Button(header="다음", title="▶", sub="다음 기기", bg=NAV_BG, accent=DIM),
    }


# ---------- 페이지 6: 주식 히트맵 (HeatTab 연동) ----------
KR_UP, KR_DOWN = (229, 72, 77), (59, 111, 245)  # 한국식: 상승 빨강, 하락 파랑


def heat_color(change: float | None, scale: float = 6.0) -> str:
    """등락률이 클수록 진하게 (±scale% 에서 최대). 주식 ±6%, 환율·원자재·금리 ±1.5%."""
    if change is None:
        return BG
    base, tint = (31, 34, 51), (KR_UP if change >= 0 else KR_DOWN)
    t = 0.25 + 0.75 * min(abs(change) / scale, 1.0) if abs(change) >= 0.02 else 0
    return "#%02x%02x%02x" % tuple(int(b + (c - b) * t) for b, c in zip(base, tint))


def page_market(view: str, quotes) -> dict[int, Button]:
    from market import VIEW_LABEL

    p: dict[int, Button] = {i: Button(bg=BG) for i in range(10)}
    if quotes is None:
        p[0] = Button(header="히트맵", title="-", sub="연결 안 됨", bg=BG, accent=RED)
        return p
    if not quotes:
        p[0] = Button(header=VIEW_LABEL.get(view, ""), title="-", sub="config 에 종목 추가", bg=BG, accent=DIM)
        return p
    for i, q in enumerate(quotes[:10]):
        if q.value is not None:  # 지표: 값을 크게, 등락을 아래에
            title, sub = q.value, q.note or ""
        else:
            title, sub = ("-" if q.change is None else f"{q.change:+.2f}%"), q.price
        p[i] = Button(header=q.name, raw_header=True, header_fg="#ffffff", title=title, sub=sub,
                      bg=heat_color(q.change, 1.5 if q.value is not None else 6.0), fg="#ffffff")
    return p

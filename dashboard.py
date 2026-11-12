"""D200 LLM 한도 + 에이전트 스튜디오 현황 대시보드 (페이지 넘김).

페이지: 1 요약 / 2 한도 그리드 / 3 스튜디오(Herdr)
하단 줄: [◀ 이전][갱신 · 길게 누르면 밝기][다음 ▶] + 오른쪽 넓은 칸 시계

실행: .venv/bin/python dashboard.py
"""

from __future__ import annotations

from pathlib import Path
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from clock import render_clock, render_market, render_message, render_timer, render_worktree_summary
from d200 import D200, SMALL_BACKGROUND, Button, InputEvent
from machines import MachineStat, machine_stats
from pages import (LLM, Limit, nav, nav_device, nav_worktrees, page_device, page_grid, page_machines, page_pomodoro,
                   page_market, page_studio, page_summary, page_worktrees)
import market
from aquarium import Aquarium
from games import Games

from config import CFG
from i18n import t
import parcels
import parcels_import
import web_credits
import updater
import intro
from sfx import ambient, play
from fireplace import Fireplace
from scenes import Beach, Rain
from mole import MOLE_HOSTS, dryrun_info, empty_trash, mole_status, refresh_dryrun, run_clean, run_purge, trash_info
from machines import MACHINES
from worktrees import Worktree, ask_tower, open_in_herdr, remove_worktree, worktrees
from pomodoro import PRESETS, Pomodoro, notify_done
from remote_agy import HOST as AGY_HOST
from remote_agy import agy_quota
import remote_agy
from remote_herdr import (TOWER_SPACE, StudioState, TowerMeta, Workspace, alert_keys, apply_ack, focus,
                          studio_state, tower_meta, tower_split, unzoom_pane, zoom_pane)
from usage import claude_usage, codex_live, codex_usage

REFRESH_SEC = 30
BRIGHTNESS_STEPS = [20, 50, 80, 100]
LONG_PRESS = 0.8
W5, WEEK = timedelta(hours=5), timedelta(days=7)
HOME_PAGE = 0  # 홈: 페이지 바로가기 + 업데이트 내용 (켜질 때 인트로 뒤, 가운데 버튼 짧게)
CLOCK_PAGES = (HOME_PAGE, 1, 2, 4)  # 넓은 칸이 시계인 페이지 (업데이트 단추 역할도 함)
PARCELS_ON = bool((CFG.get("parcels") or {}).get("enabled"))  # 택배(해외 직구) 도착 예상 페이지
# 웹으로만 보이는 크레딧 (한도 표에서 LLM 다음 열): 이름, 색
WEB_CREDITS = [(k, n, c) for k, n, c in (("flow", "FLOW", "#4285f4"), ("higgsfield", "HIGGS", "#c6f432"))
               if (CFG.get(k) or {}).get("enabled")]
PAGES = 9 if PARCELS_ON else 8
GAME_PAGE = 7  # 게임: 두더지 잡기 · 순서 기억
PARCEL_PAGE = 8 if PARCELS_ON else -1  # 택배 (게임 다음)
AQUA_PAGE = PAGES  # 어항 (넘김 순서 마지막, 화면보호기로도 사용)
GAME_TICK = 0.05
AQUA_FPS = 5
WT_PAGE = 16  # 워크트리: 작업 현황 넓은 칸에서 들어가는 하위 페이지 (넘김 순서 밖)
DEV_PAGE = 17  # 기기 상세: 머신 페이지에서 컴퓨터를 눌러 들어가는 하위 페이지
WT_POLL_SEC = 60
ARM_SEC = 10  # 길게 한 번 누른 뒤 확인 대기 시간
MACHINE_POLL_SEC = 60
STUDIO_POLL_SEC = 5
REPEAT_WINDOW = 30  # 같은 칸 반복 누름으로 보는 시간(초)


def signature(s: StudioState) -> tuple:
    """화면에 영향을 주는 스튜디오 상태 요약 (바뀌었을 때만 다시 그리기)."""
    return (s.online, tuple((w.name, w.working, w.attention, w.done, w.idle) for w in s.workspaces))


def collect_llms(pool: ThreadPoolExecutor) -> list[LLM]:
    """Claude(로컬 statusline 스냅샷), Codex(실시간), agy(config 의 agy.host) 한도를 모은다."""
    f_codex = pool.submit(codex_live)
    f_agy = pool.submit(agy_quota)
    cu = claude_usage()
    xu = f_codex.result() or codex_usage()
    ag = f_agy.result()

    def lim(used, reset, win):
        return Limit(None if used is None else 1 - used / 100, reset, win)

    claude = LLM("CLAUDE", "#d97757",
                 five=lim(cu.five_hour.used_percent, cu.five_hour.resets_at, W5),
                 week=lim(cu.seven_day.used_percent, cu.seven_day.resets_at, WEEK))
    codex = LLM("CODEX", "#10a37f", week=lim(xu.primary.used_percent, xu.primary.resets_at, WEEK))
    if xu.secondary.used_percent is not None:
        codex.five = lim(xu.secondary.used_percent, xu.secondary.resets_at, W5)
    out = [claude]
    if Path(f"{Path.home()}/.codex").exists():  # Codex 를 한 번도 안 쓴 맥이면 칸을 빼고 앞으로 당긴다
        out.append(codex)
    if not AGY_HOST:  # agy 주소를 설정하지 않았으면 표시 안 함
        return out
    agy = LLM("AGY", "#7aa2f7", login=ag is None and remote_agy.login_needed)
    for b in ag or []:  # 모델 그룹이 여럿이면 창마다 가장 빠듯한(남은 게 적은) 그룹을 보여준다
        if b.window == "5h" and (agy.five is None or b.remaining < agy.five.remaining):
            agy.five = Limit(b.remaining, b.reset, W5)
        elif b.window == "weekly" and (agy.week is None or b.remaining < agy.week.remaining):
            agy.week = Limit(b.remaining, b.reset, WEEK)
    return out + [agy]


class LoggingPool(ThreadPoolExecutor):
    """백그라운드 작업에서 난 예외를 로그에 남긴다 (조용히 묻히지 않게)."""

    def submit(self, fn, /, *args, **kwargs):
        fut = super().submit(fn, *args, **kwargs)

        def done(f):
            if f.exception():
                print(f"{datetime.now():%H:%M:%S} task error in {getattr(fn, '__name__', fn)}: {f.exception()!r}",
                      flush=True)

        fut.add_done_callback(done)
        return fut


class Dashboard:
    def __init__(self) -> None:
        if CFG.get('device') == 'mirabox':
            from mirabox import Mirabox
            self.deck = Mirabox()
        else:
            self.deck = D200()
        self.deck.on_event = self.on_event
        self.pool = LoggingPool(max_workers=8)
        self.page = 1
        self.brightness_idx = 2
        self.llms: list[LLM] = []
        self.studio = StudioState(False, [])
        self.pressed_at: dict[int, float] = {}
        self.fetch_now = threading.Event()
        self.stop = threading.Event()
        self.render_lock = threading.Lock()
        self.rendered_minute = ""
        self.blink_on = False
        self.machines: list[MachineStat] = []
        self.machines_at = 0.0
        self.raw_studio = StudioState(False, [])  # Herdr 원본 상태
        self.acked: set[tuple[str, str]] = set()  # 눌러서 확인한 알림 (터미널, 상태)
        self.last_focus: tuple[str, int, float] = ("", 0, 0.0)  # (스페이스 이름, 누른 횟수, 시각)
        self.row_names: list[str] = []  # 3페이지 가운데 줄 스튜디오 순서
        self.row_lock_until = 0.0
        self.tower_meta = TowerMeta({}, {})
        self.zoomed_pane: str | None = None  # 대시보드가 확대해 둔 총괄 pane
        self.pomo = Pomodoro.load()
        self.market_view = 0  # market.VIEWS 순서
        self.aquarium = Aquarium(int(CFG.get("aquarium_fish", 14)))  # 물고기 수 (config)
        self.fireplace = Fireplace()
        self.rain = Rain()
        self.beach = Beach()
        # 멍때리기 화면: aqua(물멍) | fire(불멍). 화면보호기는 config "screensaver_scene" (aqua·fire·번갈아 alternate)
        self.saver_cfg = CFG.get("screensaver_scene", "aqua")
        self.scene_kind = self.saver_cfg if self.saver_cfg in ("aqua", "fire", "rain", "beach") else "aqua"
        self.aqua_thread: threading.Thread | None = None
        self.aqua_entered = 0.0
        self.games = Games()
        self.intro_on = False  # 시작 인트로 재생 중
        self.intro_skip = False
        self.home_notes: list[str] = []
        self.home_fresh = False
        self.home_note_page = 0
        self.home_extra: list[tuple[int, str, str, str, str]] = []
        self.home_pick = False  # 홈에서 어항을 눌렀을 때: 물멍/불멍 고르기  # 선택 기능이 홈에 추가하는 바로가기
        self.parcels: list = []  # 택배 목록 (parcels.Parcel)
        self.parcels_at = 0.0
        self.parcels_import_at = time.time()  # 켜자마자 가져오지는 않음 (3시간 뒤부터)
        self.credits_at = 0.0
        self.parcel_sel: int | None = None  # 고른 택배 (넓은 칸에 이동 기록)
        self.parcel_off = 0  # 9개 넘으면 넘겨 보기
        self.game_thread: threading.Thread | None = None
        self.game_handled: set[int] = set()  # 누를 때 이미 처리한 칸 (뗄 때 무시)
        self.saver_from: int | None = None  # 화면보호기로 들어오기 전 페이지 (None 이면 직접 들어옴)
        self.last_input = time.time()
        self.saver_sec = float(CFG.get("screensaver_min", 10)) * 60  # 0 이면 화면보호기 끔
        self.market_quotes = None
        self.market_idx: list = []
        self.market_breadth = (0, 0)
        self.wts: list[Worktree] | None = []
        self.wts_at = 0.0
        self.wt_armed: tuple[str, str, float] | None = None  # (경로, remove|ask, 만료 시각)
        self.wt_msg: tuple[str, list[str], str, float] | None = None  # (제목, 줄들, 색, 만료 시각)
        self.device_idx = 0  # 기기 상세 페이지에서 보고 있는 컴퓨터 (MACHINES 순서)
        self.mole: dict = {}  # 이름 → MoleStatus
        self.trash: dict = {}  # 이름 → (항목 수, GB)
        self.mole_at = 0.0
        self.dev_armed: tuple[str, str, float] | None = None  # (기기 이름, purge|trash, 만료)

    @property
    def brightness(self) -> int:
        return BRIGHTNESS_STEPS[self.brightness_idx]

    # ---- 입력 ----
    def on_event(self, ev: InputEvent) -> None:
        if ev.kind != "button":
            return
        if ev.action == "press":
            self.pressed_at[ev.index] = time.time()
            if self.intro_on:  # 인트로: 아무 칸 = 건너뛰기
                self.intro_skip = True
                self.game_handled.add(ev.index)
                return
            if ev.index >= 13 and self.page in CLOCK_PAGES and updater.status()["behind"]:
                # 새 버전: 넓은 칸을 계속 누르고 있으면 업데이트 (떼면 취소)
                t = self.pressed_at[ev.index]
                threading.Timer(updater.HOLD_SEC, self.update_if_held, (ev.index, t)).start()
            if self.page == GAME_PAGE and (ev.index < 10 or ev.index >= 13 or self.games.fullscreen):  # 게임은 누르는 순간 처리
                # (화면 전체 연출 중엔 아래 줄 버튼도 게임 화면이라 페이지 넘김을 막는다)
                self.last_input = time.time()
                self.game_handled.add(ev.index)
                self.games.press(ev.index)
                self.ensure_game_loop()
                self.render_game()
            return
        if ev.action != "release":
            return
        held = time.time() - self.pressed_at.pop(ev.index, time.time())
        self.last_input = time.time()
        if ev.index in self.game_handled:
            self.game_handled.discard(ev.index)
            return
        if self.page == GAME_PAGE and ev.index in (10, 12):
            self.games.menu()  # 페이지를 떠나면 게임은 메뉴로
        if self.page == GAME_PAGE and ev.index == 11 and held < LONG_PRESS and self.games.mode != "menu":
            self.games.menu()  # 게임 중 가운데 짧게 = 메뉴로
            self.render()
            return
        if self.page == AQUA_PAGE:  # 어항: 짧게 = 먹이, 길게 = 나가기
            if held >= LONG_PRESS:
                self.leave_aquarium()
            else:
                self.scene().feed(ev.index if ev.index < 13 else 13)
            return
        if self.page == DEV_PAGE and ev.index in (10, 12):  # 기기 상세 → 뒤로(머신) / 다음 기기
            if ev.index == 10:
                self.page = 4
            else:
                self.open_device((self.device_idx + 1) % len(MACHINES))
                return
            self.render()
        elif self.page == DEV_PAGE and ev.index < 10:
            self.on_device_press(ev.index, held)
        elif self.page == 4 and ev.index < 10 and ev.index % 5 < 4:  # 머신 페이지 컴퓨터 칸 → 기기 상세
            self.open_device(ev.index % 5)
        elif self.page == WT_PAGE and ev.index in (10, 12):  # 워크트리 → 뒤로(작업 현황) / 다음(머신)
            self.page = 3 if ev.index == 10 else 4
            self.render()
        elif self.page in (1, 2) and held >= LONG_PRESS and self.login_llm(ev.index):
            # 로그인이 풀린 LLM 칸 길게: 터미널을 열어 사용자가 직접 로그인
            ok = remote_agy.open_login()
            self.toast("AGY", ["터미널에서 로그인", "끝나면 agy 종료"] if ok else ["터미널을 못 열었어요"], "#7aa2f7", 6)
        elif ev.index == 10:
            self.page = PAGES if self.page in (HOME_PAGE, 1) else self.page - 1
            if self.page == AQUA_PAGE:
                self.enter_aquarium(saver=False)
                return
            self.render()
            if self.page == 6:
                self.pool.submit(self.refresh_market)
        elif ev.index == 12:
            self.page = 1 if self.page == PAGES else self.page + 1
            if self.page == AQUA_PAGE:
                self.enter_aquarium(saver=False)
                return
            self.render()
            if self.page == 6:
                self.pool.submit(self.refresh_market)
        elif self.page == 3 and ev.index >= 13:  # 작업 현황의 넓은 칸 = 워크트리 버튼
            self.page = WT_PAGE
            self.render()
            self.pool.submit(self.refresh_worktrees)
        elif self.page == WT_PAGE and ev.index < 10:
            self.on_worktree_press(ev.index, held)
        elif self.page == 3 and ev.index < 10:
            self.on_studio_press(ev.index)
        elif self.page == 5 and (ev.index < 10 or ev.index >= 13):  # 넓은 타이머 칸(13·14)도 조작 가능
            self.on_pomodoro_press(ev.index, held)
        elif self.page == 1 and ev.index == 8 and (self.studio.attention or self.studio.done):  # 요약 스튜디오 칸: 알림 있는 곳으로
            alerts = [w for w in self.studio.workspaces if w.attention] or [w for w in self.studio.workspaces if w.done]
            self.focus_ws(alerts[0])
        elif self.page == HOME_PAGE and ev.index < 10:  # 홈 바로가기
            items = self.home_items()
            if self.home_pick:  # 어항 고르기 화면: 1번 칸 = 물멍, 3번 칸 = 불멍, 그 밖 = 돌아가기
                self.home_pick = False
                pick = {0: "aqua", 1: "fire", 3: "rain", 4: "beach"}.get(ev.index % 5)
                if pick:
                    self.go_page(AQUA_PAGE, kind=pick)
                else:
                    self.render()
            elif ev.index < len(items):
                pg = items[ev.index][0]
                if pg == AQUA_PAGE:
                    self.home_pick = True
                    self.render()
                else:
                    self.go_page(pg)
        elif self.page == HOME_PAGE and ev.index >= 13:  # 홈 넓은 칸 짧게: 다음 업데이트 내용
            if held < updater.HOLD_SEC:
                self.home_note_page += 1
                self.render()
        elif self.page in CLOCK_PAGES and ev.index >= 13:  # 시계 넓은 칸 짧게: 업데이트 안내
            st = updater.status()
            if st["behind"] and held < updater.HOLD_SEC:
                self.toast(f"새 버전 {st['behind']}개", [st["subject"][:22], "넓은 칸을 2초 누르고 있으면", "업데이트 후 다시 켜져요"],
                           "#9ece6a", 6)
            elif not st["behind"]:
                self.toast("최신 버전", ["업데이트 확인 중…" if not st["checked"] else "새 버전이 없어요"], "#7aa2f7", 3)
                self.pool.submit(updater.check, True)
        elif self.page == PARCEL_PAGE and (ev.index < 10 or ev.index >= 13):
            self.on_parcel_press(ev.index, held)
        elif self.page == 6 and ev.index < 10:  # 히트맵 칸: HeatTab 새 탭
            self.pool.submit(market.open_heattab)
        elif self.page == 6 and ev.index == 11 and held < LONG_PRESS:  # 히트맵: 가운데 짧게 = 보기 전환
            self.market_view = (self.market_view + 1) % len(market.VIEWS)
            self.market_quotes = None
            self.render()
            self.pool.submit(self.refresh_market)
        elif ev.index == 11:
            if held >= LONG_PRESS:  # 길게: 밝기 순환
                self.brightness_idx = (self.brightness_idx + 1) % len(BRIGHTNESS_STEPS)
                self.deck.set_brightness(self.brightness)
                self.render()
            else:  # 짧게: 홈(바로가기)으로 + 즉시 갱신 (멍때리기 고르기 화면에서도 홈으로)
                if self.page != HOME_PAGE or self.home_pick:
                    self.home_pick = False
                    self.go_page(HOME_PAGE)
                self.fetch_now.set()

    # ---- 인트로 · 홈 ----
    def go_page(self, page: int, kind: str | None = None) -> None:
        if page == AQUA_PAGE:
            self.enter_aquarium(saver=False, kind=kind)
            return
        self.page = page
        if page == HOME_PAGE:
            self.home_note_page = 0
        self.render()
        if page == 6:
            self.pool.submit(self.refresh_market)
        if page == WT_PAGE:
            self.pool.submit(self.refresh_worktrees)

    def login_llm(self, idx: int) -> bool:
        """요약(1페이지)·한도(2페이지)에서 idx 칸이 '로그인 필요' 상태인 LLM 칸인지."""
        if idx >= 10:
            return False
        col = idx % 5
        if self.page == 1 and col >= 3:
            return False
        return col < len(self.llms) and self.llms[col].login

    def home_items(self) -> list[tuple[int, str, str, str, str]]:
        """(페이지, 이름, 설명, 아이콘, 색)"""
        items = [(1, "요약", "한도·작업", "chart", "#7aa2f7"), (2, "한도", "LLM 상세", "hourglass", "#bb9af7"),
                 (3, "작업 현황", "에이전트", "robot", "#9ece6a"), (4, "머신", "CPU·디스크", "computer", "#73daca"),
                 (5, "뽀모도로", "집중 타이머", "tomato", "#f7768e"), (6, "주식", "히트맵", "stocks", "#e0af68"),
                 (GAME_PAGE, "게임", "8종", "gamepad", "#ff9e64")]
        if PARCELS_ON:
            items.append((PARCEL_PAGE, "택배", "도착 예상", "parcel", "#ff9e64"))
        items.append((AQUA_PAGE, "어항", "물멍 · 불멍 · 비 · 바다", "fish", "#7dcfff"))
        return (items + self.home_extra)[:10]

    def render_home(self) -> None:
        if self.home_pick:  # 물멍 / 불멍 고르기: 세로 두 칸짜리 큰 단추 두 개
            body = {i: Button(bg="#101118") for i in range(10)}
            for col, (title, sub, icon, color) in ((0, ("물멍", "어항 · 물소리", "fish", "#7dcfff")),
                                                   (1, ("불멍", "벽난로 · 장작", "fire", "#ff7a3c")),
                                                   (3, ("비멍", "비 오는 창가", "rain", "#7aa2f7")),
                                                   (4, ("바다", "노을 · 파도", "wave", "#ff9e9e"))):
                body[col] = Button(image=intro.shortcut_tile(title, sub, icon, color))
                body[col + 5] = Button(image=intro.shortcut_tile(title, sub, icon, color))
            small = render_message("멍때리기", ["물멍 · 불멍 · 비멍 · 바다 중에 골라요", "가운데 칸: 돌아가기"], "#7dcfff")
            navs = nav(self.page, PAGES, self.brightness, ("홈", f"길게: 밝기 {self.brightness}"))
            try:
                self.deck.set_buttons({**body, **navs}, small_png=small)
            except Exception as e:
                print(f"{datetime.now():%H:%M:%S} home render error: {e}", flush=True)
            return
        body = {}
        items = self.home_items()
        for i in range(10):
            if i < len(items):
                _, title, sub, icon, color = items[i]
                body[i] = Button(image=intro.shortcut_tile(title, sub, icon, color))
            else:
                body[i] = Button(bg="#16161e")
        st = updater.status()
        small = intro.home_wide(self.home_notes, self.home_fresh, intro.incoming() if st["behind"] else [],
                                st["behind"], self.home_note_page)
        if self.wt_msg and time.time() < self.wt_msg[3]:
            small = render_message(*self.wt_msg[:3])
        navs = nav(self.page, PAGES, self.brightness, ("홈", f"길게: 밝기 {self.brightness}"))
        navs[11] = Button(header="홈", title="갱신", sub=f"길게: 밝기 {self.brightness}", bg="#1f2233", accent="#565f89")
        try:
            self.deck.set_buttons({**body, **navs}, small_png=small)
        except Exception as e:
            print(f"{datetime.now():%H:%M:%S} home render error: {e}", flush=True)

    def play_intro(self) -> None:
        """켜질 때 약 3초 인트로 → 홈. 아무 칸이나 누르면 건너뜀."""
        self.home_notes, self.home_fresh = intro.whats_new(), intro.is_new()
        self.intro_on, self.intro_skip = True, False
        sub = intro.version_text()
        play("intro")
        t0 = time.time()
        try:
            while not self.intro_skip and time.time() - t0 < intro.INTRO_SEC:
                f0 = time.time()
                tiles, wide = intro.intro_frame(time.time() - t0, sub)
                with self.render_lock:
                    self.deck.set_buttons({i: Button(image=p) for i, p in tiles.items()}, small_png=wide)
                time.sleep(max(0.0, 1 / intro.FPS - (time.time() - f0)))
        except Exception as e:
            print(f"intro error: {e}", flush=True)
        self.intro_on = False
        self.page = HOME_PAGE
        intro.mark_seen()  # 다음에 켤 때는 이번 이후 바뀐 것만 '새로 바뀐 것'으로
        self.render()

    # ---- 택배 ----
    def refresh_parcels(self, force: bool = False) -> None:
        self.parcels = parcels.grouped(parcels.refresh(force))
        self.parcels_at = time.time()
        if self.page == PARCEL_PAGE:
            self.render()

    def refresh_credits(self) -> None:
        for key, _, _ in WEB_CREDITS:
            try:
                web_credits.run(key)
            except BaseException as e:  # 로그인 만료 등: 로그만 남기고 마지막 값 유지
                print(f"{datetime.now():%H:%M:%S} {key} credits: {e}", flush=True)
        if self.page == 2:
            self.render()

    def import_parcels(self) -> None:
        try:
            parcels_import.run()
        except BaseException as e:  # 로그인 만료 등: 로그만 남기고 계속
            print(f"{datetime.now():%H:%M:%S} parcels import: {e}", flush=True)
        self.refresh_parcels()

    def on_parcel_press(self, idx: int, held: float) -> None:
        shown = self.parcels[self.parcel_off:self.parcel_off + 9]
        if idx == 9 or idx >= 13:  # 요약 칸·넓은 칸: 9개씩 넘겨 보기 (한 쪽뿐이면 새로 조회)
            if len(self.parcels) > 9:
                self.parcel_off = (self.parcel_off + 9) % len(self.parcels)
                self.parcel_sel = None
                self.render()
            else:
                self.pool.submit(self.refresh_parcels, True)
            return
        if idx >= len(shown):
            return
        k = self.parcel_off + idx
        if held >= LONG_PRESS:  # 길게: 맥 브라우저에서 배송 조회 페이지 열기
            parcels.open_tracking(self.parcels[k])
            self.toast("배송 조회", [self.parcels[k].title[:16], "브라우저에서 열었어요"], "#ff9e64", 4)
            return
        self.parcel_sel = None if self.parcel_sel == k else k  # 짧게: 넓은 칸에 이동 기록
        self.render()

    def render_parcels(self) -> tuple[dict, bytes]:
        shown = self.parcels[self.parcel_off:self.parcel_off + 9]
        blink = int(time.time()) % 2 == 0
        body = {}
        for i in range(9):
            if i < len(shown):
                p = shown[i]
                body[i] = Button(image=parcels.parcel_tile(p.title, p.stage, parcels.when_text(p), blink,
                                                           self.parcel_sel == self.parcel_off + i))
            else:
                body[i] = Button(bg="#16161e")
        coming = [p for p in self.parcels if p.stage < parcels.STAGE["도착"]]
        today = sum(1 for p in coming if p.days_left() == 0)
        week = sum(1 for p in coming if (p.days_left() or 0) <= 7)
        body[9] = Button(image=parcels.summary_tile(len(coming), today, week))
        sel = self.parcel_sel
        small = parcels.wide_detail(self.parcels[sel]) if sel is not None and sel < len(self.parcels) \
            else parcels.wide_summary(self.parcels)
        return body, small

    # ---- 워크트리(하위 페이지) ----
    def refresh_worktrees(self) -> None:
        self.wts = worktrees()
        self.wts_at = time.time()
        if self.page == WT_PAGE:
            self.render()

    def armed_now(self) -> tuple[str | None, str | None]:
        if self.wt_armed and time.time() < self.wt_armed[2]:
            return self.wt_armed[0], self.wt_armed[1]
        return None, None

    # ---- 기기 상세(하위 페이지) ----
    def refresh_mole(self) -> None:
        got = []
        for name, host in MOLE_HOSTS.items():
            st = mole_status(host)
            if st:
                self.mole[name] = st
                got.append(f"{name}={st.health}")
                refresh_dryrun(host)  # 정리 가능 용량: 6시간마다 백그라운드 측정 (상세 페이지를 안 열어도)
        self.mole_at = time.time()
        print(f"{datetime.now():%H:%M:%S} mole: {' '.join(got) or 'no response'}", flush=True)
        if self.page in (4, DEV_PAGE):
            self.render()

    def refresh_device(self) -> None:
        name = MACHINES[self.device_idx][0]
        host = MOLE_HOSTS.get(name)
        if host:
            st = mole_status(host)
            if st:
                self.mole[name] = st
            info = trash_info(host)
            if info:
                self.trash[name] = info
            refresh_dryrun(host)  # 6시간 넘었으면 백그라운드 측정
        if self.page == DEV_PAGE:
            self.render()

    def open_device(self, idx: int) -> None:
        if not 0 <= idx < len(MACHINES):
            return
        self.device_idx, self.page, self.dev_armed = idx, DEV_PAGE, None
        self.render()
        self.pool.submit(self.refresh_device)

    def on_device_press(self, idx: int, held: float) -> None:
        name = MACHINES[self.device_idx][0]
        host = MOLE_HOSTS.get(name)
        if idx not in (7, 8, 9) or not host:
            return
        action = {7: "clean", 8: "purge", 9: "trash"}[idx]
        if held < LONG_PRESS:  # 짧게: 설명만
            dry, tr = dryrun_info(host), self.trash.get(name)
            if action == "clean":
                size = f"{dry['clean_gb']:.1f}GB" if dry.get("clean_gb") is not None else "측정 전"
                self.toast("캐시·로그 정리", [f"{name} · {size}", "앱 캐시·로그·임시 파일 (mo clean)", "길게 2번 눌러 실행"], "#ff9e64")
            elif action == "purge":
                size = f"{dry['purge_gb']:.1f}GB · {dry.get('purge_items', 0)}개" if dry.get("purge_gb") is not None else "측정 전"
                self.toast("빌드 산출물 정리", [f"{name} · {size}", "node_modules·.venv·dist 등", "길게 2번 눌러 실행"], "#ff9e64")
            else:
                size = (f"{tr[1]:.1f}GB · {tr[0]}개" if tr[0] >= 0 else f"{tr[1]:.1f}GB") if tr else "-"
                self.toast("휴지통 비우기", [f"{name} · {size}", "영구 삭제됩니다", "길게 2번 눌러 실행"], "#ff9e64")
            return
        armed = self.dev_armed if self.dev_armed and time.time() < self.dev_armed[2] else None
        if not armed or armed[:2] != (name, action):  # 길게 첫 번째: 확인 대기
            self.dev_armed = (name, action, time.time() + ARM_SEC)
            what = {"clean": "캐시·로그 정리 (mo clean)", "purge": "빌드 산출물 정리 (mo purge)",
                    "trash": "휴지통 영구 비우기"}[action]
            self.toast("확인 필요", [name, what, f"{ARM_SEC}초 안에 길게 한 번 더"], "#f7768e", ARM_SEC)
            return
        self.dev_armed = None  # 길게 두 번째: 실행
        doing = {"clean": "캐시 정리 중 (몇 분 걸릴 수 있어요)", "purge": "산출물 정리 중 (몇 분 걸릴 수 있어요)",
                 "trash": "휴지통 비우는 중"}[action]
        self.toast("실행 중…", [name, doing], "#e0af68", 900)

        def run() -> None:
            ok, msg = {"clean": run_clean, "purge": run_purge, "trash": empty_trash}[action](host)
            self.toast("완료" if ok else "실패", [name, msg], "#9ece6a" if ok else "#f7768e", 15)
            self.refresh_device()

        self.pool.submit(run)

    def update_if_held(self, idx: int, pressed: float) -> None:
        if self.pressed_at.get(idx) != pressed:  # 이미 뗐으면 취소
            return
        self.toast("업데이트 중…", ["새 버전을 받는 중", "잠시 뒤 다시 켜져요"], "#e0af68", 120)
        ok, msg = updater.update()
        if ok:
            self.toast("업데이트 완료", [msg, "다시 켜는 중…"], "#9ece6a", 30)
            updater.restart_soon()
        else:
            self.toast("업데이트 못 함", [msg, "터미널에서 git pull 해 주세요"], "#f7768e", 15)

    def toast(self, title: str, lines: list[str], color: str = "#bb9af7", sec: float = 8) -> None:
        self.wt_msg = (title, lines, color, time.time() + sec)
        self.render()

    def on_worktree_press(self, idx: int, held: float) -> None:
        items = self.wts or []
        if idx >= len(items):
            return
        w = items[idx]
        if held < LONG_PRESS:  # 짧게: Herdr 에서 열기
            self.wt_armed = None
            tower = next((x for x in self.raw_studio.workspaces if x.name == TOWER_SPACE), None)
            self.pool.submit(open_in_herdr, w, tower.space_id if tower else None)
            return
        action = "remove" if w.can_remove else "ask"
        path, armed_action = self.armed_now()
        if path != w.path:  # 길게 첫 번째: 확인 대기
            self.wt_armed = (w.path, action, time.time() + ARM_SEC)
            what = "워크트리 삭제 (브랜치는 유지)" if action == "remove" else "리드 에이전트에게 정리 요청 전송"
            self.toast("확인 필요", [f"{w.repo}/{w.name}", what, f"{ARM_SEC}초 안에 길게 한 번 더"], "#f7768e", ARM_SEC)
            return
        self.wt_armed = None  # 길게 두 번째: 실행
        self.toast("실행 중…", [f"{w.repo}/{w.name}"], "#e0af68", 30)

        def run() -> None:
            ok, out = remove_worktree(w) if armed_action == "remove" else ask_tower(w)
            done = "삭제 완료" if armed_action == "remove" else "총괄에게 전송함"
            self.toast(done if ok else "실패", [f"{w.repo}/{w.name}", out[:40]] if not ok else [f"{w.repo}/{w.name}"],
                       "#9ece6a" if ok else "#f7768e")
            self.refresh_worktrees()

        self.pool.submit(run)

    # ---- 어항 (7페이지 · 화면보호기) ----
    # 멍때리기 장면: 이름 → (장면, 배경음, 짧게 누르면)
    SCENES = {"aqua": ("aquarium", "amb_water", "먹이"), "fire": ("fireplace", "amb_fire", "장작"),
              "rain": ("rain", "amb_rain", "번개"), "beach": ("beach", "amb_waves", "큰 파도")}

    def scene(self):
        return getattr(self, self.SCENES.get(self.scene_kind, self.SCENES["aqua"])[0])

    def enter_aquarium(self, saver: bool, kind: str | None = None) -> None:
        if kind:
            self.scene_kind = kind
        elif saver and self.saver_cfg == "alternate":  # 화면보호기: 장면을 차례로 바꿔 가며
            order = list(self.SCENES)
            self.scene_kind = order[(order.index(self.scene_kind) + 1) % len(order)] if self.scene_kind in order else "aqua"
        elif saver and self.saver_cfg in self.SCENES:
            self.scene_kind = self.saver_cfg
        ambient.start(self.SCENES.get(self.scene_kind, self.SCENES["aqua"])[1])
        self.saver_from = self.page if saver else None
        self.page = AQUA_PAGE
        self.aqua_entered = time.time()
        if not (self.aqua_thread and self.aqua_thread.is_alive()):
            self.aqua_thread = threading.Thread(target=self.aqua_loop, daemon=True)
            self.aqua_thread.start()

    def leave_aquarium(self, to: int | None = None) -> None:
        """나가기: 화면보호기로 들어왔으면 원래 페이지로, 직접 들어왔으면 멍때리기 고르기 화면으로."""
        if to:
            self.page = to
        elif self.saver_from is not None:
            self.page = self.saver_from
        else:
            self.page, self.home_pick = HOME_PAGE, True
        self.saver_from = None
        self.render()

    def aqua_loop(self) -> None:
        """어항 페이지에 있는 동안 초당 AQUA_FPS 번 화면을 다시 보낸다."""
        while self.page == AQUA_PAGE and not self.stop.is_set():
            t0 = time.time()
            self.scene().step(1 / AQUA_FPS)
            self.render()
            time.sleep(max(0.0, 1 / AQUA_FPS - (time.time() - t0)))
        ambient.stop()  # 페이지를 떠나면 배경음도 끝

    # ---- 게임 (7페이지) ----
    def ensure_game_loop(self) -> None:
        if not (self.game_thread and self.game_thread.is_alive()):
            self.game_thread = threading.Thread(target=self.game_loop, daemon=True)
            self.game_thread.start()

    def game_loop(self) -> None:
        """게임 중에는 짧은 간격으로 시간을 진행하고, 화면이 바뀔 때만 다시 보낸다."""
        last = None
        while self.page == GAME_PAGE and self.games.active and not self.stop.is_set():
            self.games.tick()
            key = (tuple(self.games.tiles().items()), self.games.wide_key())
            if key != last:
                last = key
                self.render_game()
            time.sleep(GAME_TICK)
        if self.page == GAME_PAGE:
            self.render_game()  # 끝 화면

    def render_game(self) -> None:
        with self.render_lock:
            try:
                t0 = time.time()
                body = {i: Button(image=p) for i, p in self.games.tiles().items()}
                middle = ("메뉴", "게임 그만") if self.games.mode != "menu" else None
                self.deck.set_buttons({**nav(GAME_PAGE, PAGES, self.brightness, middle), **body},  # 게임이 아래 줄까지 그리면 그걸 쓴다
                                      small_png=self.games.wide())
                if time.time() - t0 > 0.4:  # 느린 장면 기록 (버벅임 진단용)
                    print(f"{datetime.now():%H:%M:%S} slow game frame {self.games.mode}: {time.time() - t0:.2f}s", flush=True)
            except Exception as e:
                print(f"{datetime.now():%H:%M:%S} game render error: {e}", flush=True)

    # ---- 주식 히트맵(6페이지) ----
    def refresh_market(self) -> None:
        if not market.MARKET_ENABLED:
            return
        view = market.VIEWS[self.market_view]
        self.market_quotes = market.view_data(view)
        self.market_idx = market.indices()
        self.market_breadth = market.breadth()
        if self.page == 6:
            self.render()

    # ---- 뽀모도로(5페이지) ----
    def on_pomodoro_press(self, idx: int, held: float) -> None:
        if self.pomo.state == "setup":
            if idx < len(PRESETS):
                self.pomo.start(PRESETS[idx])
        elif self.pomo.state == "done":
            self.pomo.reset()
        elif self.pomo.state == "paused" and idx == 9:  # 일시정지 화면의 '취소' 칸
            self.pomo.reset()
        elif held >= LONG_PRESS:  # 길게: 취소 (장치가 지원하면)
            self.pomo.reset()
        else:  # 짧게: 일시정지/재개
            self.pomo.toggle_pause()
        self.render()

    # ---- 작업 현황(3페이지) ----
    def raw_tower(self) -> Workspace | None:
        return next((w for w in self.raw_studio.workspaces if w.name == TOWER_SPACE), None)

    def studio_row(self) -> list[Workspace]:
        """가운데 줄 5칸: 결정 > 완료 > 작업 중 > 창 순서. 최근 누른 뒤 30초 동안은 위치 고정."""
        others = [w for w in self.studio.workspaces if w.name != TOWER_SPACE]
        size = 5 if any(w.name == TOWER_SPACE for w in self.studio.workspaces) else 10
        if time.time() < self.row_lock_until and self.row_names:
            by_name = {w.name: w for w in others}
            row = [by_name[n] for n in self.row_names if n in by_name]
            return row + [w for w in others if w.name not in self.row_names][: size - len(row)]
        order = {w.name: i for i, w in enumerate(others)}
        row = sorted(others, key=lambda w: (-w.attention, -w.done, -w.working, order[w.name]))[:size]
        self.row_names = [w.name for w in row]
        return row

    def on_studio_press(self, idx: int) -> None:
        tower = next((w for w in self.studio.workspaces if w.name == TOWER_SPACE), None)
        if not tower:  # 리드 스페이스 없음(훅 방식): 10칸 모두 프로젝트
            row = self.studio_row()
            if idx < len(row):
                self.focus_ws(row[idx])
            return
        if idx < 4:  # 리드 탭 pane: 그 에이전트로 이동 + 알림 확인
            if not tower:
                return
            panes, _ = tower_split(tower)
            if idx < len(panes):
                m = panes[idx]
                self.acked |= {(m.term, "attention"), (m.term, "done")}
                self.set_studio(self.raw_studio)
                self.render()
                # 처음 누름: 이동 + 확대 / 같은 pane 다시 누름: 원래 배치로
                if self.zoomed_pane and self.zoomed_pane == m.pane:
                    self.pool.submit(unzoom_pane, m.pane)
                    self.zoomed_pane = None
                else:
                    self.pool.submit(zoom_pane, m.term, m.pane, self.zoomed_pane)
                    self.zoomed_pane = m.pane
        elif idx == 4:  # 기타 총괄 탭들
            raw = self.raw_tower()
            if raw:
                self.focus_ws(tower_split(raw)[1])
        else:
            row = self.studio_row()
            if idx - 5 < len(row):
                self.focus_ws(row[idx - 5])

    def focus_ws(self, ws) -> None:
        """처음 누르면 우선 대상으로, 같은 칸을 30초 안에 다시 누르면 다음 탭으로."""
        name, count, at = self.last_focus
        step = count + 1 if name == ws.name and time.time() - at < REPEAT_WINDOW else 0
        self.last_focus = (ws.name, step, time.time())
        self.row_lock_until = time.time() + REPEAT_WINDOW  # 반복 누름 동안 칸 위치 고정
        # 원본 상태 기준으로 이 스페이스 알림을 확인 처리 → 깜빡임 즉시 끄기
        raw = next((w for w in self.raw_studio.workspaces if w.name == ws.name), ws)
        self.acked |= alert_keys(raw)
        self.set_studio(self.raw_studio)
        self.render()
        self.pool.submit(focus, raw, step)

    def set_studio(self, raw: StudioState) -> None:
        """원본 상태 저장 + 이미 사라진 알림의 확인 기록 정리 + 확인한 알림 제외한 화면용 상태."""
        self.raw_studio = raw
        current = set().union(*(alert_keys(w) for w in raw.workspaces)) if raw.workspaces else set()
        self.acked &= current
        self.studio = apply_ack(raw, self.acked)

    # ---- 화면 ----
    def clock_status(self) -> list[tuple[str, str]]:
        """시계 하단 칩: 스튜디오 작업/확인 수 + 지금 여유 있는 LLM."""
        chips: list[tuple[str, str]] = []
        if self.studio.online:
            chips.append((f"작업 {self.studio.working}", "#7aa2f7"))
            chips.append((f"결정 {self.studio.attention}", "#e0af68" if self.studio.attention else "#565f89"))
            chips.append((f"완료 {self.studio.done}", "#9ece6a" if self.studio.done else "#565f89"))
        else:
            chips.append(("스튜디오 OFF", "#f7768e"))
        up = updater.status()["behind"]
        if up:
            chips.insert(0, (f"새 버전 {up}", "#9ece6a"))
        today = sum(1 for p in self.parcels if p.stage < parcels.STAGE["도착"] and p.days_left() == 0)
        if today:
            chips.append((f"택배 오늘 {today}", "#ff9e64"))
        if self.pomo.state in ("running", "paused"):  # 타이머 진행 중이면 다른 페이지 시계에도 표시
            chips.append((f"집중 {int(self.pomo.remaining() // 60) + 1}분", "#f7768e"))
        else:
            ranked = sorted((m for m in self.llms if m.binding()), key=lambda m: m.binding().remaining, reverse=True)
            if ranked:
                chips.append((f"추천 {ranked[0].name}", "#9ece6a"))
        return chips

    def render(self) -> None:
        if self.intro_on:
            return
        if self.page == HOME_PAGE:
            with self.render_lock:
                self.render_home()
            return
        if self.page == GAME_PAGE:
            self.render_game()
            return
        with self.render_lock:
            now = datetime.now(timezone.utc)
            if self.page == AQUA_PAGE:
                hint = f"짧게 눌러 {self.SCENES.get(self.scene_kind, self.SCENES['aqua'])[2]} · 길게 눌러 나가기" \
                    if time.time() - self.aqua_entered < 4 else None
                tiles, wide = self.scene().tiles(hint)
                try:
                    self.deck.set_buttons({i: Button(image=p) for i, p in tiles.items()}, small_png=wide)
                except Exception as e:
                    print(f"{datetime.now():%H:%M:%S} aqua render error: {e}", flush=True)
                return
            if self.page == PARCEL_PAGE:
                body, small = self.render_parcels()
                try:
                    self.deck.set_buttons({**body, **nav(self.page, PAGES, self.brightness, ("택배", "길게: 조회"))},
                                          small_png=small)
                except Exception as e:
                    print(f"{datetime.now():%H:%M:%S} parcel render error: {e}", flush=True)
                return
            if self.page == 1:
                body = page_summary(self.llms, self.studio, now, self.blink_on)
            elif self.page == 2:
                body = page_grid(self.llms, now, [(n, c, d) for k, n, c in WEB_CREDITS if (d := web_credits.load(k))])
            elif self.page == 3:
                body = page_studio(self.studio, self.blink_on, self.studio_row(), self.tower_meta)
            elif self.page == 4:
                dry = {n: dryrun_info(h) for n, h in MOLE_HOSTS.items()}
                body = page_machines(self.machines, now, self.mole, dry)
            elif self.page == 5:
                body = page_pomodoro(self.pomo, self.blink_on)
            elif self.page == 6:
                body = page_market(market.VIEWS[self.market_view], self.market_quotes)
            elif self.page == DEV_PAGE:
                name, host = MACHINES[self.device_idx][0], MOLE_HOSTS.get(MACHINES[self.device_idx][0])
                m = next((x for x in self.machines if x.name == name), None)
                armed = self.dev_armed[1] if self.dev_armed and self.dev_armed[0] == name and time.time() < self.dev_armed[2] else None
                body = page_device(m, self.mole.get(name), dryrun_info(host) if host else {}, self.trash.get(name), armed) \
                    if m else {}
            else:
                body = page_worktrees(self.wts, *self.armed_now())
            try:
                if self.page == 5:
                    small = render_timer(self.pomo.remaining(), self.pomo.state,
                                         self.pomo.end_at if self.pomo.state == "running" else None)
                elif self.page == 6:
                    small = render_market(self.market_idx or market.indices(), self.market_breadth,
                                          market.VIEW_LABEL[market.VIEWS[self.market_view]])
                elif self.page == 3:  # 시계 대신 워크트리 요약 (누르면 워크트리 페이지)
                    small = render_worktree_summary(self.wts)
                elif self.page == DEV_PAGE:
                    if self.wt_msg and time.time() < self.wt_msg[3]:
                        small = render_message(*self.wt_msg[:3])
                    else:
                        name = MACHINES[self.device_idx][0]
                        lines = ["아래 오른쪽 두 칸: 길게 2번 = 실행", "짧게 = 설명"] if name in MOLE_HOSTS else ["Mole 이 설치되지 않은 기기"]
                        small = render_message(name, lines)
                elif self.page == WT_PAGE:
                    if self.wt_msg and time.time() < self.wt_msg[3]:
                        small = render_message(*self.wt_msg[:3])
                    else:
                        small = render_message("워크트리", ["짧게: Herdr 에서 열기",
                                                         "길게 2번: 정리 가능 → 삭제",
                                                         "길게 2번: 그 외 → 총괄에 정리 요청"])
                elif self.wt_msg and time.time() < self.wt_msg[3]:  # 알림(업데이트 등)이 있으면 잠깐 대신 표시
                    small = render_message(*self.wt_msg[:3])
                else:
                    small = render_clock(status=self.clock_status())
                if self.page == WT_PAGE:
                    navs = nav_worktrees(self.brightness)
                elif self.page == DEV_PAGE:
                    navs = nav_device(self.brightness)
                elif self.page == 6:
                    nxt = market.VIEW_LABEL[market.VIEWS[(self.market_view + 1) % len(market.VIEWS)]]
                    navs = nav(self.page, PAGES, self.brightness, ("보기", f"→ {nxt}"))
                else:
                    navs = nav(self.page, PAGES, self.brightness)
                self.deck.set_buttons({**body, **navs}, small_png=small)
                self.rendered_minute = datetime.now().strftime("%H:%M")
            except Exception as e:
                print(f"{datetime.now():%H:%M:%S} render error: {e}", flush=True)

    def fetch(self) -> None:
        try:
            if time.time() - self.machines_at >= MACHINE_POLL_SEC or self.page == 4:
                self.machines = machine_stats(self.pool)
                self.machines_at = time.time()
            if time.time() - self.wts_at >= WT_POLL_SEC:
                self.pool.submit(self.refresh_worktrees)
            if self.page == 6:
                self.pool.submit(self.refresh_market)
            if PARCELS_ON and parcels_import.PROFILE.exists() and time.time() - self.parcels_import_at > 3 * 3600:
                self.parcels_import_at = time.time()  # 3시간마다 알리 주문 다시 가져오기 (전용 프로필로 화면 없이)
                self.pool.submit(self.import_parcels)
            if WEB_CREDITS and time.time() - self.credits_at > web_credits.POLL_SEC:
                self.credits_at = time.time()  # 30분마다 Flow·Higgsfield 크레딧 (전용 프로필로 화면 없이)
                self.pool.submit(self.refresh_credits)
            if PARCELS_ON and (time.time() - self.parcels_at > parcels.POLL_SEC or
                               (self.page == PARCEL_PAGE and time.time() - self.parcels_at > 300)):
                self.parcels_at = time.time()
                self.pool.submit(self.refresh_parcels)
            if self.page == DEV_PAGE:
                self.machines = machine_stats(self.pool)
                self.pool.submit(self.refresh_device)
            elif time.time() - self.mole_at >= MACHINE_POLL_SEC:
                self.pool.submit(self.refresh_mole)
            f_studio = self.pool.submit(studio_state)
            f_meta = self.pool.submit(tower_meta)  # 60초 캐시
            self.llms = collect_llms(self.pool)
            self.set_studio(f_studio.result())
            self.tower_meta = f_meta.result()
        except Exception as e:  # 수집 실패해도 데몬은 계속
            print(f"{datetime.now():%H:%M:%S} fetch error: {e}", flush=True)

    def run(self) -> None:
        self.deck.start()
        self.deck.set_brightness(self.brightness)
        self.deck.set_small_window(mode=SMALL_BACKGROUND)  # 넓은 칸 = 커스텀 시계 이미지
        print(f"{type(self.deck).__name__} dashboard started (Ctrl+C to quit)", flush=True)
        updater.start_background()
        self.play_intro()
        while not self.stop.is_set() and not self.deck.disconnected.is_set():
            self.fetch()
            self.render()
            # 1초 단위: 끊김 감지, 결정 필요 칸 깜빡임, 스튜디오 5초 폴링, 분 바뀌면 시계 갱신
            for sec in range(REFRESH_SEC):
                if self.fetch_now.wait(1) or self.stop.is_set() or self.deck.disconnected.is_set():
                    break
                dirty = False
                if sec % STUDIO_POLL_SEC == STUDIO_POLL_SEC - 1:
                    new = studio_state()
                    if signature(new) != signature(self.raw_studio):
                        self.set_studio(new)
                        dirty = True
                if self.pomo.check_finished():  # 타이머 끝: 알림 + 5페이지로
                    notify_done(self.pomo.duration / 60)
                    self.page, dirty = 5, True
                if self.page == 5 and self.pomo.state == "running":
                    dirty = True  # 매초 남은 시간·칸 갱신
                if (self.page == 5 and self.pomo.state == "done") or \
                        ((self.studio.attention or self.studio.done) and self.page in (1, 3)):
                    self.blink_on, dirty = not self.blink_on, True
                elif self.blink_on:
                    self.blink_on, dirty = False, True
                # 화면보호기: 오래 입력이 없으면 어항, 알림이 생기면 빠져나오기
                alert = self.studio.attention or self.studio.done or self.pomo.state == "done"
                if self.page == AQUA_PAGE:
                    if alert and self.saver_from is not None:
                        self.leave_aquarium(5 if self.pomo.state == "done" else 3)
                    continue
                if self.page == GAME_PAGE and self.games.active:
                    continue  # 게임 중엔 화면보호기·주기 갱신 없음
                if self.saver_sec and not alert and time.time() - self.last_input > self.saver_sec:
                    self.enter_aquarium(saver=True)
                    continue
                # 워크트리: 확인 대기·결과 메시지가 만료되면 원래 화면으로
                if self.wt_armed and time.time() >= self.wt_armed[2]:
                    self.wt_armed, dirty = None, dirty or self.page == WT_PAGE
                if self.dev_armed and time.time() >= self.dev_armed[2]:
                    self.dev_armed, dirty = None, dirty or self.page == DEV_PAGE
                if self.wt_msg and time.time() >= self.wt_msg[3]:
                    self.wt_msg, dirty = None, dirty or self.page in (WT_PAGE, DEV_PAGE)
                if dirty or datetime.now().strftime("%H:%M") != self.rendered_minute:
                    self.render()
            self.fetch_now.clear()
        self.deck.close()
        if self.deck.disconnected.is_set():
            print(f"{datetime.now():%H:%M:%S} device disconnected, exiting", flush=True)
            raise SystemExit(1)  # launchd KeepAlive 가 재시작


def main() -> None:
    try:
        dash = Dashboard()
    except RuntimeError as e:  # 장치 미연결: launchd 가 잠시 후 다시 시도
        print(f"{datetime.now():%H:%M:%S} {e}", flush=True)
        raise SystemExit(1)

    def _quit(*_):
        dash.stop.set()
        dash.fetch_now.set()

    signal.signal(signal.SIGINT, _quit)
    signal.signal(signal.SIGTERM, _quit)
    dash.run()


if __name__ == "__main__":
    main()

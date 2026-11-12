"""뽀모도로 타이머 상태 (대시보드 재시작에도 이어지도록 파일에 저장)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass

from i18n import t

STATE_PATH = os.path.expanduser("~/.cache/d200/pomodoro.json")
PRESETS = [5, 10, 15, 20, 25, 30, 45, 50, 60, 90]  # 분, 위 10칸 순서


@dataclass
class Pomodoro:
    state: str = "setup"  # setup | running | paused | done
    duration: float = 0.0  # 초
    end_at: float = 0.0  # running 일 때 끝나는 시각 (epoch)
    left_at_pause: float = 0.0  # paused 일 때 남은 초

    # ---- 계산 ----
    def remaining(self, now: float | None = None) -> float:
        now = now or time.time()
        if self.state == "running":
            return max(0.0, self.end_at - now)
        if self.state == "paused":
            return self.left_at_pause
        return 0.0

    def fraction(self) -> float:
        """남은 비율 0~1."""
        return self.remaining() / self.duration if self.duration else 0.0

    # ---- 조작 ----
    def start(self, minutes: int) -> None:
        self.state, self.duration = "running", minutes * 60.0
        self.end_at = time.time() + self.duration
        self.save()

    def toggle_pause(self) -> None:
        if self.state == "running":
            self.state, self.left_at_pause = "paused", self.remaining()
        elif self.state == "paused":
            self.state, self.end_at = "running", time.time() + self.left_at_pause
        self.save()

    def reset(self) -> None:
        self.state, self.duration, self.end_at, self.left_at_pause = "setup", 0.0, 0.0, 0.0
        self.save()

    def check_finished(self) -> bool:
        """running 인데 시간이 다 됐으면 done 으로 바꾸고 True."""
        if self.state == "running" and self.remaining() <= 0:
            self.state = "done"
            self.save()
            return True
        return False

    # ---- 저장 ----
    def save(self) -> None:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as fp:
            json.dump(asdict(self), fp)

    @classmethod
    def load(cls) -> "Pomodoro":
        try:
            p = cls(**json.load(open(STATE_PATH)))
            p.check_finished()  # 꺼져 있는 사이 끝났으면 done
            return p
        except Exception:
            return cls()


def notify_done(minutes: float) -> None:
    """맥 알림 + 소리 3번."""
    if os.name == 'nt':
        import winsound
        winsound.MessageBeep()
        return
    msg = t(f"{minutes:.0f}분 집중 완료! 잠깐 쉬어가세요.", f"{minutes:.0f} min focus done! Take a short break.")
    title = t("뽀모도로", "Pomodoro")
    subprocess.Popen(["osascript", "-e", f'display notification "{msg}" with title "{title}" sound name "Glass"'])
    subprocess.Popen(["/bin/sh", "-c", "for i in 1 2 3; do afplay /System/Library/Sounds/Glass.aiff; done"])

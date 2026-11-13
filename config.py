"""설정 로더.

config.json(개인 설정, git 에 올리지 않음)을 읽고, 없으면 config.example.json 을 쓴다.
선택 기능(Herdr 스튜디오, agy, 원격 머신, Mole)은 설정에 있을 때만 켜진다.
"""

from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def _load() -> dict:
    for name in ("config.json", "config.example.json"):
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fp:
                return json.load(fp)
    return {}


CFG = _load()

# 컴퓨터 목록: [{"name": 표시 이름, "ssh": ssh 대상 또는 null(이 맥), "mole": Mole 설치 여부}]
MACHINES_CFG: list[dict] = CFG.get("machines", [{"name": "This Mac", "ssh": None, "mole": False}])
# 외장 드라이브: [{"volume": 볼륨 이름, "machine": 연결된 컴퓨터 표시 이름}]
EXTERNAL_DRIVES_CFG: list[dict] = CFG.get("external_drives", [])

# Herdr 스튜디오(에이전트 작업 현황): 없으면 비활성
STUDIO: dict = CFG.get("studio") or {}
STUDIO_ENABLED = bool(STUDIO.get("enabled") and STUDIO.get("host"))
STUDIO_HOST: str = STUDIO.get("host", "")
TOWER_SPACE: str = STUDIO.get("tower_space", "")
TOWER_MAIN_TAB: str = STUDIO.get("tower_main_tab", "")
LEAD_PANE: str = STUDIO.get("lead_pane", "")
WORKTREE_GLOBS: list[str] = STUDIO.get("worktree_globs", [])

# 에이전트 현황 출처: "herdr"(Herdr 앱) 또는 "hooks"(Claude Code·Codex 훅, IDE·터미널 상관없음)
AGENT_SOURCE: str = CFG.get("agent_source", "herdr" if STUDIO_ENABLED else "hooks")
# 훅 상태를 읽을 컴퓨터: null = 이 맥, 그 외 ssh 대상
HOOK_HOSTS: list[str | None] = (CFG.get("hooks") or {}).get("hosts", [None])

# agy(Antigravity CLI) 할당량: SSH 대상 또는 이 PC는 "local"
AGY: dict = CFG.get("agy") or {}
AGY_HOST: str | None = AGY.get("host") if AGY.get("enabled") else None

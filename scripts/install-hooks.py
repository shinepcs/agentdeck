#!/usr/bin/env python3
"""에이전트 상태 훅 설치/제거 (훅 방식: VS Code·Cursor·터미널 등 어디서 돌든 상태 수집).

  python3 scripts/install-hooks.py            # Claude Code 훅 설치
  python3 scripts/install-hooks.py --codex    # + Codex notify 연결 (기존 notify 는 이어서 실행되도록 감쌈)
  python3 scripts/install-hooks.py --uninstall

기존 훅은 건드리지 않고 우리 항목만 추가/제거한다. 바꾸기 전에 .bak-agentdeck 백업을 만든다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
import tomllib
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from i18n import t  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "agent_hook.py")
PYTHON = sys.executable if os.name == 'nt' else 'python3'
CLAUDE_CMD = f'"{PYTHON}" "{HOOK}" claude'
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
CODEX_CONFIG = os.path.expanduser("~/.codex/config.toml")
EVENTS = {  # 이벤트 → matcher (도구 이벤트만 "*")
    "SessionStart": None, "UserPromptSubmit": None, "PreToolUse": "*", "PostToolUse": "*",
    "PermissionRequest": "*", "Notification": None, "Stop": None, "StopFailure": None, "SessionEnd": None,
}


def backup(path: str) -> None:
    if os.path.exists(path):
        target = path + '.bak-agentdeck'
        if os.path.exists(target):
            target += f'-{time.time_ns()}'
        shutil.copy2(path, target)


def is_ours(entry: dict) -> bool:
    return any("agent_hook.py" in (h.get("command") or "") for h in entry.get("hooks", []))


def claude(install: bool) -> None:
    data = json.loads(Path(CLAUDE_SETTINGS).read_text(encoding='utf-8')) if os.path.exists(CLAUDE_SETTINGS) else {}
    hooks = data.setdefault("hooks", {})
    for ev, matcher in EVENTS.items():
        arr = [e for e in hooks.get(ev, []) if not is_ours(e)]  # 우리 것 제거 (재설치 시 중복 방지)
        if install:
            entry = {"hooks": [{"type": "command", "command": CLAUDE_CMD, "timeout": 5}]}
            if matcher:
                entry = {"matcher": matcher, **entry}
            arr.append(entry)
        if arr:
            hooks[ev] = arr
        else:
            hooks.pop(ev, None)
    backup(CLAUDE_SETTINGS)
    os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
    with open(CLAUDE_SETTINGS, "w", encoding='utf-8') as fp:
        json.dump(data, fp, indent=2, ensure_ascii=False)
    print(t("설치" if install else "제거", "Installed" if install else "Removed"), t("Claude Code 훅:", "Claude Code hooks:"), CLAUDE_SETTINGS)


def codex(install: bool) -> None:
    if not os.path.exists(CODEX_CONFIG):
        print(t("Codex 설정 없음:", "No Codex config:"), CODEX_CONFIG)
        return
    text = Path(CODEX_CONFIG).read_text(encoding='utf-8')
    m = re.search(r"^notify[ \t]*=[ \t]*(\[.*?\])[ \t]*(?:#[^\r\n]*)?$", text, re.M | re.S)
    current = tomllib.loads(text).get('notify')
    if current is not None and not m:
        raise ValueError('Cannot locate the existing notify setting safely')
    ours = [PYTHON, HOOK, "codex", "--"]
    if current and len(current) >= 4 and current[1].endswith("agent_hook.py"):
        original = current[4:]  # 이미 우리 래퍼: 원래 명령만 꺼냄
    else:
        original = current or []
    new = (ours + original) if install else original
    line = "notify = " + json.dumps(new, ensure_ascii=False) if new else ""
    if m:
        text = text[:m.start()] + line + text[m.end():]
    elif line:
        text = line + "\n" + text
    tomllib.loads(text)  # Validate before touching the existing config.
    backup(CODEX_CONFIG)
    Path(CODEX_CONFIG).write_text(text, encoding='utf-8')
    print(t("설치" if install else "제거", "Installed" if install else "Removed"), "Codex notify:", CODEX_CONFIG,
          f'(preserved {len(original)} existing command arguments)')


if __name__ == "__main__":
    uninstall = "--uninstall" in sys.argv
    claude(not uninstall)
    if "--codex" in sys.argv or uninstall:
        codex(not uninstall)
